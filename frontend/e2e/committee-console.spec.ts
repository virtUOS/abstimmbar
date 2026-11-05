/** Committee console: signal tone and notice when a vote closes by itself;
 *  console and beamer window close when the meeting ends (started from the
 *  meeting page, so both are script-opened). */
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

test('auto-close signal; console and beamer close with the meeting', async ({ page, context, browser, trackRoom }) => {
  // Count tones: every oscillator the page starts.
  await context.addInitScript(() => {
    const w = window as unknown as { __tones: number; AudioContext: unknown };
    w.__tones = 0;
    class FakeAudio {
      state = 'running';
      currentTime = 0;
      destination = {};
      resume() { return Promise.resolve(); }
      createGain() {
        return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} };
      }
      createOscillator() {
        return { frequency: { value: 0 }, type: '', connect() {}, stop() {}, start() { w.__tones += 1; } };
      }
    }
    w.AudioContext = FakeAudio;
  });
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };

  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Konsole', kind: 'committee' });
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
  await api('post', '/api/questions/', {
    question_set: meeting.id, kind: 'resolution', text: { de: 'Der Antrag wird angenommen.' },
  });

  // Start from the meeting page: the console opens in a new tab.
  await page.goto(`/sets/${meeting.id}`);
  const consolePromise = context.waitForEvent('page');
  await page.getByRole('button', { name: 'Sitzung beginnen' }).click();
  const startNow = page.getByRole('button', { name: 'Jetzt beginnen' });
  if (await startNow.isVisible({ timeout: 1500 }).catch(() => false)) await startNow.click();
  const consolePage = await consolePromise;
  await consolePage.waitForURL(new RegExp(`/sets/${meeting.id}/meeting$`));

  // Open the beamer window from the console.
  const beamerPromise = consolePage.waitForEvent('popup');
  await consolePage.getByRole('button', { name: 'Beamer-Fenster öffnen' }).click();
  const beamer = await beamerPromise;
  await expect(beamer.getByTestId('beamer-picture').or(beamer.locator('body'))).toBeVisible();

  // Two members vote; the last vote closes it: notice and tone.
  await api('post', `/api/meetings/${meeting.id}/invites/`);
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  // Members take their seats by opening their links.
  const members: Page[] = [];
  for (const invite of summary.invites) {
    const ctx = await browser.newContext({ locale: 'de-DE' });
    const p = await ctx.newPage();
    await p.goto(invite.url);
    await expect(p.getByText('Bitte warten Sie auf die nächste Abstimmung.')).toBeVisible();
    members.push(p);
  }
  const item = consolePage.getByTestId('console-item').first();
  await item.getByRole('button', { name: /Antrag wird angenommen/ }).click();
  await item.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await expect(consolePage.getByTestId('beamer-progress')).toHaveText('0 von 2 haben abgestimmt');
  expect(await consolePage.evaluate(() => (window as unknown as { __tones: number }).__tones)).toBe(0);
  for (const p of members) {
    await p.getByRole('button', { name: 'Ja', exact: true }).click();
    await expect(p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  }
  await expect(consolePage.getByTestId('auto-closed-notice')).toContainText('automatisch geschlossen');
  await expect
    .poll(() => consolePage.evaluate(() => (window as unknown as { __tones: number }).__tones))
    .toBe(2);

  // End the meeting in the console: console and beamer close, the meeting page follows.
  await consolePage.getByRole('button', { name: 'Sitzung beenden' }).click();
  await consolePage.getByRole('dialog').getByRole('button', { name: 'Sitzung beenden' }).click();
  await expect.poll(() => consolePage.isClosed()).toBe(true);
  await expect.poll(() => beamer.isClosed()).toBe(true);
  await expect(page.getByTestId('meeting-ended-note')).toBeVisible();
  for (const p of members) await p.context().close();

  // Opened directly, the page cannot close itself: ended view with a link back.
  const direct = await context.newPage();
  await direct.addInitScript(() => { window.close = () => {}; }); // browsers refuse it here
  await direct.goto(`/sets/${meeting.id}/meeting`);
  await expect(direct.getByText('Die Sitzung ist beendet.')).toBeVisible();
  await expect(direct.getByRole('link', { name: 'Zur Sitzung' })).toHaveAttribute('href', `/sets/${meeting.id}`);
});

test('a draft meeting opened directly is not closed and does not announce an end', async ({ page, context, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.json();
  };
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Entwurf', kind: 'committee' });
  trackRoom(room.id);
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Entwurf', scheduled_at: '2030-01-15T10:00:00Z',
  });
  await api('post', '/api/questions/', {
    question_set: meeting.id, kind: 'resolution', text: { de: 'Antrag' },
  });

  // The meeting page stays put: no reload, no "ended" note.
  await page.goto(`/sets/${meeting.id}`);
  await expect(page.getByRole('button', { name: 'Sitzung beginnen' })).toBeVisible();
  await page.evaluate(() => { (window as unknown as { __marker: number }).__marker = 1; });

  for (const path of [`/sets/${meeting.id}/meeting`, `/sets/${meeting.id}/meeting/beamer`]) {
    const other = await context.newPage();
    await other.addInitScript(() => {
      (window as unknown as { __closes: number }).__closes = 0;
      window.close = () => { (window as unknown as { __closes: number }).__closes += 1; };
    });
    await other.goto(path);
    await expect(other.getByText('Die Sitzung hat noch nicht begonnen.')).toBeVisible();
    await expect(other.getByRole('link', { name: 'Zur Sitzung' })).toBeVisible();
    await other.waitForTimeout(600);
    expect(await other.evaluate(() => (window as unknown as { __closes: number }).__closes)).toBe(0);
    expect(other.isClosed()).toBe(false);
  }
  await page.waitForTimeout(600);
  expect(await page.evaluate(() => (window as unknown as { __marker?: number }).__marker)).toBe(1);
  await expect(page.getByTestId('meeting-ended-note')).toHaveCount(0);
});

test('console reached by the same-tab link and refused to close returns to the meeting page', async ({ page, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Rueckkehr', kind: 'committee' });
  trackRoom(room.id);
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Rueckkehr', scheduled_at: '2030-01-15T10:00:00Z',
  });
  await api('post', '/api/questions/', {
    question_set: meeting.id, kind: 'resolution', text: { de: 'Antrag' },
  });
  await api('post', `/api/meetings/${meeting.id}/start/`);

  await page.addInitScript(() => { window.close = () => {}; }); // browsers refuse it here
  await page.goto(`/sets/${meeting.id}`);
  await page.getByRole('link', { name: 'Sitzung leiten' }).click();
  await page.waitForURL(new RegExp(`/sets/${meeting.id}/meeting$`));
  await page.getByRole('button', { name: 'Sitzung beenden' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Sitzung beenden' }).click();
  await page.waitForURL(new RegExp(`/sets/${meeting.id}$`));
  await expect(page.getByTestId('meeting-ended-note')).toBeVisible();
  await expect(page.getByText('Beendet', { exact: true }).first()).toBeVisible();
});
