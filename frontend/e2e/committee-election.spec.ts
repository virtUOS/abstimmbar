/** Committee election (Gremien-Raum, PR 4a): three candidates, two votes per
 *  person, a runoff between the top two, and the protocol with both rounds.
 *
 *  Setup goes through the API as `demo`; the room is titled "E2E …" and
 *  deleted afterwards. Members open their personal links in fresh
 *  anonymous browser contexts. */
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

test('election: two votes per person, runoff, protocol', async ({ page, browser, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };

  // 1. Room, groups, two voters, meeting with an election of 3 candidates.
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Wahl', kind: 'committee' });
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
    question_set: meeting.id, kind: 'election', max_votes: 2, cumulate: false,
    text: { de: 'Wahl der Schriftführung' },
    options: [{ text: { de: 'Clara Alt' } }, { text: { de: 'Dirk Bauer' } }, { text: { de: 'Eva Cramer' } }],
  });
  await api('post', `/api/meetings/${meeting.id}/start/`);
  await api('post', `/api/meetings/${meeting.id}/invites/`);
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  const linkOf = (email: string): string =>
    summary.invites.find((i: { member: { email: string } }) => i.member.email === email).url;

  const open = async (email: string) => {
    const context = await browser.newContext({ locale: 'de-DE' });
    const p = await context.newPage();
    await p.goto(linkOf(email));
    await expect(p.getByText('Bitte warten Sie auf die nächste Abstimmung.')).toBeVisible();
    return { context, p };
  };
  const anna = await open('anna@example.org');
  const ben = await open('ben@example.org');

  // 2. The chair shows the election and opens the vote.
  await page.goto(`/sets/${meeting.id}/meeting`);
  const item = page.getByTestId('console-item').first();
  await item.getByRole('button', { name: /Wahl der Schriftführung/ }).click();
  await item.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  const progress = page.getByTestId('beamer-progress');
  await expect(progress).toHaveText('0 von 2 haben abgestimmt');

  // 3. Anna gives two votes, Ben one (the second is an abstention).
  const counter = anna.p.getByRole('status').filter({ hasText: /Stimmen vergeben/ });
  await expect(counter).toHaveText('0 von 2 Stimmen vergeben');
  await expect(anna.p.getByRole('button', { name: 'Stimmen abgeben' })).toBeDisabled();
  await anna.p.getByRole('button', { name: 'Clara Alt', exact: true }).click();
  await anna.p.getByRole('button', { name: 'Dirk Bauer', exact: true }).click();
  await expect(counter).toHaveText('2 von 2 Stimmen vergeben');
  // The limit is reached: the third candidate cannot be picked.
  await expect(anna.p.getByRole('button', { name: 'Eva Cramer', exact: true })).toBeDisabled();
  // The "BAR" wordmark in the shared header (live/base.html) is a known
  // brand-colour contrast finding outside this feature; everything else must pass.
  const { violations } = await new AxeBuilder({ page: anna.p })
    .exclude('header .bar')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(violations.map((v) => ({ rule: v.id, nodes: v.nodes.slice(0, 5).map((n) => n.target.join(' ')) }))).toEqual([]);
  await anna.p.getByRole('button', { name: 'Stimmen abgeben' }).click();
  await expect(anna.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await expect(progress).toHaveText('1 von 2 haben abgestimmt');
  await expect(page.getByTestId('beamer-result')).toHaveCount(0);

  await ben.p.getByRole('button', { name: 'Clara Alt', exact: true }).click();
  await expect(ben.p.getByRole('status').filter({ hasText: /Stimmen vergeben/ })).toHaveText('1 von 2 Stimmen vergeben');
  await ben.p.getByRole('button', { name: 'Stimmen abgeben' }).click();

  // 4. As the last voter Ben closes the vote: counts incl. abstentions.
  const result = page.getByTestId('beamer-result');
  await expect(result).toBeVisible();
  const row = (label: string) => result.getByRole('listitem').filter({ hasText: new RegExp(`^${label}`) }).first();
  await expect(row('Clara Alt')).toContainText('2');
  await expect(row('Dirk Bauer')).toContainText('1');
  await expect(row('Eva Cramer')).toContainText('0');
  await expect(row('Enthaltung')).toContainText('1');

  // 5. Runoff with the proposed candidates (preselected).
  await item.getByTestId('runoff-start').click();
  const dialog = page.getByTestId('runoff-dialog');
  const picks = dialog.getByTestId('runoff-candidate');
  await expect(picks).toHaveCount(3);
  await expect(picks.nth(0)).toBeChecked();
  await expect(picks.nth(1)).toBeChecked();
  await expect(picks.nth(2)).not.toBeChecked();
  await dialog.getByTestId('runoff-confirm').click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('beamer-runoff')).toBeVisible();

  // 6. Members see two candidates and vote with a single tap.
  for (const m of [anna, ben]) {
    await expect(m.p.getByRole('button', { name: 'Clara Alt', exact: true })).toBeVisible();
    await expect(m.p.getByRole('button', { name: 'Dirk Bauer', exact: true })).toBeVisible();
    await expect(m.p.getByRole('button', { name: 'Eva Cramer', exact: true })).toHaveCount(0);
  }
  await anna.p.getByRole('button', { name: 'Clara Alt', exact: true }).click();
  await expect(anna.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await ben.p.getByRole('button', { name: 'Dirk Bauer', exact: true }).click();
  await expect(page.getByTestId('beamer-result')).toBeVisible();
  await expect(row('Clara Alt')).toContainText('1');
  await expect(row('Dirk Bauer')).toContainText('1');

  // 7. End the meeting; the protocol shows both rounds with their seals.
  await api('post', `/api/meetings/${meeting.id}/end/`);
  await page.goto(`/sets/${meeting.id}/protocol`);
  const protocolItem = page.getByTestId('protocol-item');
  await expect(protocolItem).toHaveCount(1);
  await expect(protocolItem).toContainText('Wahl der Schriftführung');
  await expect(protocolItem.getByText('1. Wahlgang', { exact: true })).toBeVisible();
  await expect(protocolItem.getByText('Stichwahl (2. Wahlgang)', { exact: true })).toBeVisible();
  await expect(protocolItem.getByTestId('protocol-round')).toHaveCount(2);
  await expect(protocolItem.locator('a.font-mono').last()).toContainText('-W2');

  for (const c of [anna, ben]) await c.context.close();
});
