/** Committee room: the chair reviews and confirms the translation of a
 *  motion; English-speaking members see the original text (with a hint)
 *  until then. Room "E2E …", deleted afterwards. */
import type { Page } from '@playwright/test';
import { test, expect, API_BASE_URL, csrfToken } from './fixtures';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 900 } });

async function login(page: Page): Promise<void> {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) {
      json.onboarding_tour_seen = true;
      json.easy_mode = false;
    }
    await route.fulfill({ response, json });
  });
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL('http://localhost:5174/**');
}

test('translation review: badge, confirm, edit resets, English ballot page', async ({ page, browser, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post' | 'patch', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };

  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Übersetzung', kind: 'committee' });
  trackRoom(room.id);
  const templates = await api('get', '/api/committee-templates/');
  await api('post', '/api/committee-groups/apply-template/', { room: room.id, template: templates[0].id });
  const groups = await api('get', `/api/committee-groups/?room=${room.id}`);
  const voters = groups.find((g: { is_observer: boolean }) => !g.is_observer);
  const members = await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: voters.id, role: 'voting', text: 'Ben Beispiel <ben@example.org>',
  });
  const ben = (Array.isArray(members) ? members : members.members ?? members.created)[0];
  await api('patch', `/api/committee-members/${ben.id}/`, { language: 'en' });
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Sitzung', scheduled_at: '2030-01-15T10:00:00Z',
  });
  const resolution = (de: string, en: string) =>
    api('post', '/api/questions/', {
      question_set: meeting.id, kind: 'resolution', text: { de, en },
    });
  const first = await resolution('Der Haushalt wird genehmigt.', 'The budget is approved.');
  const second = await resolution('Die Satzung wird geändert.', 'The statutes are amended.');

  // 1. Before the start, the editor of a saved item shows the open review.
  await page.goto(`/sets/${meeting.id}/questions/${first.id}`);
  await expect(page.getByTestId('translation-status')).toHaveText('Übersetzung nicht bestätigt');

  await api('post', `/api/meetings/${meeting.id}/start/`);
  await api('post', `/api/meetings/${meeting.id}/invites/`);
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  const link: string = summary.invites[0].url;

  // 2. English member, translation of the first item unconfirmed: German
  //    text plus hint, never the English wording.
  const member = await browser.newContext({ locale: 'en-US' });
  const mp = await member.newPage();
  await mp.goto(link);
  await page.goto(`/sets/${meeting.id}/meeting`);
  const items = page.getByTestId('console-item');
  await expect(items).toHaveCount(2);
  await expect(items.first().getByTestId('translation-status')).toHaveText('Übersetzung nicht bestätigt');
  await items.first().getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await expect(mp.getByText('Der Haushalt wird genehmigt.')).toBeVisible();
  await expect(mp.getByText('The translation has not been confirmed yet')).toBeVisible();
  await expect(mp.getByText('The budget is approved.')).toHaveCount(0);
  await mp.getByRole('button', { name: 'Yes', exact: true }).click();
  await expect(page.getByTestId('beamer-result').first()).toBeVisible();

  // 3. Second item: review dialog shows both languages; confirm.
  const row = items.nth(1);
  await row.getByTestId('translation-review').click();
  const dialog = page.getByTestId('translation-dialog');
  await expect(dialog).toContainText('Die Satzung wird geändert.');
  await expect(dialog).toContainText('The statutes are amended.');
  await dialog.getByRole('button', { name: 'Übersetzung bestätigen' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row.getByTestId('translation-status')).toHaveText('Übersetzung bestätigt');

  // 4. Editing the English text invalidates the confirmation.
  await row.getByRole('button', { name: 'Text ändern' }).click();
  const edit = page.getByRole('dialog', { name: 'Text ändern' });
  await edit.getByRole('tab', { name: /^en/i }).click();
  const editor = edit.locator('[contenteditable="true"]').first();
  await editor.click();
  await page.keyboard.press('End');
  await page.keyboard.type(' (revised)');
  await edit.getByRole('button', { name: 'Speichern', exact: true }).click();
  await expect(row.getByTestId('translation-status')).toHaveText('Übersetzung nicht bestätigt');

  // 5. Confirm again: the member sees the English wording when it opens.
  await row.getByTestId('translation-review').click();
  await expect(page.getByTestId('translation-dialog')).toContainText('(revised)');
  await page.getByRole('button', { name: 'Übersetzung bestätigen' }).click();
  await expect(row.getByTestId('translation-status')).toHaveText('Übersetzung bestätigt');
  await row.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await expect(mp.getByText('The statutes are amended. (revised)')).toBeVisible();
  await expect(mp.getByText('The translation has not been confirmed yet')).toHaveCount(0);
  await expect(mp.getByText('Die Satzung wird geändert.')).toHaveCount(0);

  await member.close();
});
