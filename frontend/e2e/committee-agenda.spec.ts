/** Committee agenda (Gremien-Raum): TOPs with vote labels (3 / 3a / 3b), a TOP
 *  without a vote on the beamer, a resolution added by the chair, and an
 *  en bloc vote.
 *
 *  Setup goes through the API as `demo`; the room is titled "E2E …" and
 *  deleted afterwards. Members open their personal links in fresh
 *  anonymous browser contexts. */
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

test('agenda: TOPs, spontaneous resolution, en bloc vote', async ({ page, browser, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };

  // 1. Room, members, meeting with an agenda: TOP 1 without a vote,
  //    TOP 2 with two resolutions, TOP 3 with one. Sections and questions
  //    share one position sequence, so they are created in outline order.
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Tagesordnung', kind: 'committee' });
  trackRoom(room.id);
  const templates = await api('get', '/api/committee-templates/');
  await api('post', '/api/committee-groups/apply-template/', { room: room.id, template: templates[0].id });
  const groups = await api('get', `/api/committee-groups/?room=${room.id}`);
  const voters = groups.find((g: { is_observer: boolean }) => !g.is_observer);
  await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: voters.id, role: 'voting',
    text: 'Anna Muster <anna@example.org>, Ben Beispiel <ben@example.org>',
  });
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Sitzung', scheduled_at: '2030-01-15T10:00:00Z',
  });
  const section = (title: string) =>
    api('post', '/api/sections/', { question_set: meeting.id, title: { de: title } });
  const resolution = (text: string, sectionId: number) =>
    api('post', '/api/questions/', {
      question_set: meeting.id, kind: 'resolution', text: { de: text }, section: sectionId,
    });
  await section('Bericht');
  const haushalt = await section('Haushalt');
  await resolution('Der Haushalt wird genehmigt.', haushalt.id);
  await resolution('Die Rücklage wird aufgestockt.', haushalt.id);
  const satzung = await section('Satzung');
  await resolution('Die Satzung wird geändert.', satzung.id);

  await api('post', `/api/meetings/${meeting.id}/start/`);
  await api('post', `/api/meetings/${meeting.id}/invites/`);
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  const linkOf = (email: string): string =>
    summary.invites.find((i: { member: { email: string } }) => i.member.email === email).url;

  const anna = await (async () => {
    const context = await browser.newContext({ locale: 'de-DE' });
    const p = await context.newPage();
    await p.goto(linkOf('anna@example.org'));
    return { context, p };
  })();
  await expect(anna.p.getByText('Bitte warten Sie auf die nächste Abstimmung.')).toBeVisible();

  // 2. The editor numbers the TOPs and labels the votes 2a, 2b and 3.
  await page.goto(`/sets/${meeting.id}`);
  const labels = page.getByTestId('vote-label');
  await expect(labels).toHaveText(['2a', '2b', '3']);
  await expect(page.getByText('TOP 1', { exact: true })).toBeVisible();
  await expect(page.getByText('TOP 2', { exact: true })).toBeVisible();
  await expect(page.getByText('TOP 3', { exact: true })).toBeVisible();

  // 3. The chair shows TOP 1 (no vote): beamer and Anna's page show it.
  await page.goto(`/sets/${meeting.id}/meeting`);
  const tops = page.getByTestId('console-top');
  await tops.first().getByRole('button', { name: /Bericht/ }).click();
  await expect(page.getByRole('heading', { name: 'Bericht', level: 1 })).toBeVisible();
  await expect(anna.p.getByText('TOP 1: Bericht')).toBeVisible();

  // 4. A resolution added in TOP 3: it becomes 3b, the former one 3a.
  const top3 = tops.nth(2);
  await top3.getByRole('button', { name: '+ Beschluss' }).click();
  await top3.getByLabel('Beschlusstext').fill('Änderungsantrag');
  await top3.getByRole('button', { name: 'Hinzufügen', exact: true }).click();
  const items = page.getByTestId('console-item');
  await expect(items).toHaveCount(4);
  await expect(items.nth(2)).toContainText('TOP 3a');
  await expect(items.nth(2)).toContainText('Die Satzung wird geändert.');
  await expect(items.nth(3)).toContainText('TOP 3b');
  await expect(items.nth(3)).toContainText('Änderungsantrag');

  // 5. Combine 2a and 2b into one en bloc vote.
  await page.getByRole('button', { name: 'Abstimmungen zusammenfassen …' }).click();
  await page.getByRole('checkbox', { name: 'TOP 2a' }).check();
  await page.getByRole('checkbox', { name: 'TOP 2b' }).check();
  await page.getByRole('button', { name: 'En bloc abstimmen (2)' }).click();
  await expect(page.getByTestId('beamer-progress')).toHaveText('0 von 1 haben abgestimmt');
  await expect(anna.p.getByText('Eine Stimme für alle diese Beschlüsse.')).toBeVisible();
  await expect(anna.p.getByText('Der Haushalt wird genehmigt.')).toBeVisible();
  await expect(anna.p.getByText('Die Rücklage wird aufgestockt.')).toBeVisible();

  // 6. While the vote is open, no other TOP can be shown.
  const header = tops.first().getByRole('button', { name: /Bericht/ });
  await expect(header).toBeDisabled();
  await expect(header).toHaveAttribute('title', 'Es läuft noch eine andere Abstimmung.');

  // 7. Anna votes yes; closing the vote closes both resolutions.
  await anna.p.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(anna.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await page.getByRole('button', { name: 'Abstimmung schließen' }).click();
  await expect(page.getByTestId('beamer-result').first()).toBeVisible();
  await expect(items.nth(0)).toContainText('Der Haushalt wird genehmigt.');
  await expect(page.getByRole('button', { name: 'Abstimmung schließen' })).toHaveCount(0);
  await expect(items.nth(1)).toContainText('en bloc mit TOP 2a');
  await expect(header).toBeEnabled();

  await anna.context.close();
});
