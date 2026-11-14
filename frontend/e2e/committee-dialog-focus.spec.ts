/** Dialog focus handling (Gremien-Raum, PR 4c): Tab stays inside the dialog
 *  and Escape returns focus to the button that opened it. Uses the invite-mail
 *  dialog; the room is titled "E2E …" and deleted afterwards. */
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

test('dialog keeps focus inside and restores it on close', async ({ page, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Fokus', kind: 'committee' });
  trackRoom(room.id);
  const templates = await api('get', '/api/committee-templates/');
  await api('post', '/api/committee-groups/apply-template/', { room: room.id, template: templates[0].id });
  const groups = await api('get', `/api/committee-groups/?room=${room.id}`);
  const voters = groups.find((g: { is_observer: boolean }) => !g.is_observer);
  await api('post', '/api/committee-members/', {
    room: room.id, group: voters.id, role: 'voting', name: 'Anna Fokus', email: 'anna@example.org',
  });
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Sitzung Fokus', scheduled_at: '2030-01-15T10:00:00Z',
  });

  await page.goto(`/sets/${meeting.id}`);
  await page.getByRole('button', { name: 'Links erzeugen' }).click();
  await expect(page.getByTestId('invite-row')).toHaveCount(1);
  const opener = page.getByRole('button', { name: 'Per E-Mail einladen' });
  await opener.click();
  const dialog = page.getByRole('dialog', { name: 'Per E-Mail einladen' });
  await expect(dialog).toBeVisible();

  const inside = () => page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'));
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab');
    expect(await inside(), `Tab #${i + 1} left the dialog`).toBe(true);
  }
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Shift+Tab');
    expect(await inside(), `Shift+Tab #${i + 1} left the dialog`).toBe(true);
  }

  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});
