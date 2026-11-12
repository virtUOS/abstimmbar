/** Committee invite mail (Gremien-Raum, PR 4b): the chair sends the personal
 *  meeting links by e-mail from the links table. Members without an address
 *  are named; a second send only reaches not-yet-mailed members unless
 *  "send again" is ticked.
 *
 *  The dev stack uses Django's console e-mail backend (MAIL_ENABLED=1), so
 *  nothing leaves the machine. Setup goes through the API as `demo`; the room
 *  is titled "E2E …" and deleted afterwards. */
import type { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
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

test('invite mail: send links, report members without address, resend', async ({ page, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };

  // 1. Room with two members with an address and one without, a meeting.
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Mail', kind: 'committee' });
  trackRoom(room.id);
  const templates = await api('get', '/api/committee-templates/');
  await api('post', '/api/committee-groups/apply-template/', { room: room.id, template: templates[0].id });
  const groups = await api('get', `/api/committee-groups/?room=${room.id}`);
  const voters = groups.find((g: { is_observer: boolean }) => !g.is_observer);
  await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: voters.id, role: 'voting',
    text: 'Anna Muster <anna@example.org>, Ben Beispiel <ben@example.org>',
  });
  await api('post', '/api/committee-members/', {
    room: room.id, group: voters.id, role: 'voting', name: 'Carla Ohne', email: '',
  });
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Sitzung Mail', scheduled_at: '2030-01-15T10:00:00Z',
  });

  // 2. Generate the links; the mail button appears next to the CSV export.
  await page.goto(`/sets/${meeting.id}`);
  await page.getByRole('button', { name: 'Links erzeugen' }).click();
  const rows = page.getByTestId('invite-row');
  await expect(rows).toHaveCount(3);
  await page.getByRole('button', { name: 'Per E-Mail einladen' }).click();

  // 3. The dialog: subject prefilled, two recipients, one without address.
  const dialog = page.getByRole('dialog', { name: 'Per E-Mail einladen' });
  await expect(dialog.getByLabel('Betreff')).toBeFocused();
  await expect(dialog.getByLabel('Betreff')).toHaveValue('Einladung: E2E Sitzung Mail');
  await expect(dialog.getByTestId('mail-recipients')).toHaveText('Geht an 2 Mitglieder');
  await expect(dialog.getByText('1 ohne E-Mail-Adresse – bitte Link kopieren.')).toBeVisible();
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(violations.map((v) => ({ rule: v.id, nodes: v.nodes.slice(0, 5).map((n) => n.target.join(' ')) }))).toEqual([]);

  // Escape closes without sending.
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(rows.filter({ hasText: 'E-Mail:' })).toHaveCount(0);

  // 4. Send: status line and the mail date in the rows of Anna and Ben.
  await page.getByRole('button', { name: 'Per E-Mail einladen' }).click();
  await dialog.getByLabel('Nachricht (optional)').fill('Bitte pünktlich sein.');
  await dialog.getByRole('button', { name: 'Senden' }).click();
  await expect(dialog).toHaveCount(0);
  const status = page.getByTestId('mail-status');
  await expect(status).toContainText('2 E-Mails verschickt.');
  await expect(status).toContainText('Ohne E-Mail-Adresse: Carla Ohne');
  await expect(status).not.toContainText('Nicht zugestellt');
  await expect(rows.filter({ hasText: 'Anna Muster' })).toContainText('E-Mail:');
  await expect(rows.filter({ hasText: 'Ben Beispiel' })).toContainText('E-Mail:');
  await expect(rows.filter({ hasText: 'Carla Ohne' })).not.toContainText('E-Mail:');

  // 5. Again: nobody left unless "send again" is ticked; the old status
  //    line is cleared when the dialog opens.
  await page.getByRole('button', { name: 'Per E-Mail einladen' }).click();
  await expect(status).toBeEmpty();
  await expect(dialog.getByTestId('mail-recipients')).toHaveText('Geht an 0 Mitglieder');
  await expect(dialog.getByRole('button', { name: 'Senden' })).toBeDisabled();
  await dialog.getByLabel('Auch an bereits Eingeladene erneut senden').check();
  await expect(dialog.getByTestId('mail-recipients')).toHaveText('Geht an 2 Mitglieder');
  // An empty subject blocks sending.
  await dialog.getByLabel('Betreff').fill('  ');
  await expect(dialog.getByRole('button', { name: 'Senden' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Abbrechen' }).click();
  await expect(dialog).toHaveCount(0);

  // 6. A member added after the links were generated is counted: opening
  //    the dialog creates the missing link first (no reload).
  await api('post', '/api/committee-members/', {
    room: room.id, group: voters.id, role: 'voting', name: 'Dora Neu', email: 'dora@example.org',
  });
  await page.getByRole('button', { name: 'Per E-Mail einladen' }).click();
  await expect(dialog.getByTestId('mail-recipients')).toHaveText('Geht an 1 Mitglied');
  await expect(rows).toHaveCount(4);

  // 7. Rate limit and recipient cap show German texts (responses stubbed,
  //    so the real hourly budget is not used up).
  const mailUrl = `${API_BASE_URL}/api/meetings/${meeting.id}/invites/mail/`;
  await page.route(mailUrl, (route) => route.fulfill({
    status: 429, json: { detail: 'Request was throttled. Expected available in 3599 seconds.' },
  }));
  await dialog.getByRole('button', { name: 'Senden' }).click();
  await expect(dialog.getByRole('alert')).toHaveText(
    'Zu viele E-Mail-Versände. Bitte versuchen Sie es später erneut.',
  );
  await page.unroute(mailUrl);
  await page.route(mailUrl, (route) => route.fulfill({
    status: 400, json: { detail: 'Too many recipients for one send.', code: 'too_many_recipients' },
  }));
  await dialog.getByRole('button', { name: 'Senden' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Zu viele Empfänger für einen Versand.');
  await page.unroute(mailUrl);
  await dialog.getByRole('button', { name: 'Abbrechen' }).click();
  await expect(dialog).toHaveCount(0);
});
