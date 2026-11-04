/** Committee voting (Gremien-Raum, part 2): a secret resolution from the
 *  chair's console through to the closed count, a reset, and an observer.
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

test('secret resolution: vote, close, reset, observer', async ({ page, browser, trackRoom }) => {
  await login(page);
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api = async (method: 'get' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };

  // 1. Room, groups, members, observer, meeting with two items.
  const room = await api('post', '/api/rooms/', { title: 'E2E Gremium Abstimmung', kind: 'committee' });
  trackRoom(room.id);
  const templates = await api('get', '/api/committee-templates/');
  await api('post', '/api/committee-groups/apply-template/', { room: room.id, template: templates[0].id });
  const groups = await api('get', `/api/committee-groups/?room=${room.id}`);
  const voters = groups.find((g: { is_observer: boolean }) => !g.is_observer);
  const observers = groups.find((g: { is_observer: boolean }) => g.is_observer);
  await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: voters.id, role: 'voting',
    text: 'Anna Muster <anna@example.org>, Ben Beispiel <ben@example.org>',
  });
  await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: observers.id, role: 'voting', text: 'Olga Beobachtung <olga@example.org>',
  });
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Sitzung', scheduled_at: '2030-01-15T10:00:00Z',
  });
  const resolution = await api('post', '/api/questions/', {
    question_set: meeting.id, kind: 'resolution', text: { de: 'Der Antrag wird angenommen.' },
  });
  await api('post', '/api/questions/', {
    question_set: meeting.id, kind: 'open_text', text: { de: 'Anmerkungen?' },
  });
  // The editor's preview shows the ballot; a vote there stays in the page.
  await page.goto(`${API_BASE_URL}/g/preview/${resolution.id}/`);
  await expect(page.getByText('Vorschau: So sehen Mitglieder den Stimmzettel.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(page.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await page.getByRole('button', { name: 'Noch einmal' }).click();
  await expect(page.getByRole('button', { name: 'Enthaltung', exact: true })).toBeVisible();

  await api('post', `/api/meetings/${meeting.id}/start/`);
  await api('post', `/api/meetings/${meeting.id}/invites/`);
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  const inviteOf = (email: string) =>
    summary.invites.find((i: { member: { email: string } }) => i.member.email === email);
  const linkOf = (email: string): string => inviteOf(email).url;

  // 2. Anna and Ben enter via their links, each in an anonymous context.
  //    Ben's page gets a controllable clock (readmission poll, step 8).
  const open = async (email: string, clock = false) => {
    const context = await browser.newContext({ locale: 'de-DE' });
    const p = await context.newPage();
    if (clock) await p.clock.install();
    await p.goto(linkOf(email));
    return { context, p };
  };
  const anna = await open('anna@example.org');
  const ben = await open('ben@example.org', true);
  await expect(anna.p.getByText('Bitte warten Sie auf die nächste Abstimmung.')).toBeVisible();
  await expect(ben.p.getByText('Bitte warten Sie auf die nächste Abstimmung.')).toBeVisible();

  // 3. The chair shows item 1 and opens the vote.
  await page.goto(`/sets/${meeting.id}/meeting`);
  const item = page.getByTestId('console-item').first();
  await item.getByRole('button', { name: /Antrag wird angenommen/ }).click();
  await item.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  const progress = page.getByTestId('beamer-progress');
  await expect(progress).toHaveText('0 von 2 haben abgestimmt');
  // While the vote is open, no other item can be shown.
  const other = page.getByTestId('console-item').nth(1).getByRole('button', { name: /Anmerkungen/ });
  await expect(other).toBeDisabled();
  await expect(other).toHaveAttribute('title', 'Es läuft noch eine andere Abstimmung.');

  // 4. Anna votes yes; the beamer shows participation, no counts.
  await anna.p.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(anna.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await expect(progress).toHaveText('1 von 2 haben abgestimmt');
  await expect(page.getByTestId('beamer-result')).toHaveCount(0);

  // 5. Ben abstains; closing shows the count.
  await ben.p.getByRole('button', { name: 'Enthaltung', exact: true }).click();
  await expect(ben.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await item.getByRole('button', { name: 'Abstimmung schließen' }).click();
  const result = page.getByTestId('beamer-result');
  await expect(result).toBeVisible();
  const row = (label: string) => result.getByRole('listitem').filter({ hasText: new RegExp(`^${label}`) }).first();
  await expect(row('Ja')).toContainText('1');
  await expect(row('Nein')).toContainText('0');
  await expect(row('Enthaltung')).toContainText('1');

  // While another vote is open, the closed one cannot be reset.
  const second = page.getByTestId('console-item').nth(1);
  await other.click();
  await second.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  const resetButton = item.getByRole('button', { name: 'Abstimmung zurücksetzen …' });
  await expect(resetButton).toBeDisabled();
  await expect(resetButton).toHaveAttribute('title', 'Es läuft noch eine andere Abstimmung.');
  await second.getByRole('button', { name: 'Abstimmung schließen' }).click();
  await expect(resetButton).toBeEnabled();

  // 6. Reset with a comment and reopen: Anna sees the buttons again.
  await item.getByRole('button', { name: 'Abstimmung zurücksetzen …' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Kommentar (Pflicht)').fill('Technischer Fehler');
  await dialog.getByRole('button', { name: 'Zurücksetzen' }).click();
  await expect(dialog).toHaveCount(0);
  await item.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await expect(progress).toHaveText('0 von 2 haben abgestimmt');
  await expect(anna.p.getByRole('button', { name: 'Ja', exact: true })).toBeVisible();

  // 7. The observer cannot vote.
  const observer = await open('olga@example.org');
  await expect(observer.p.getByText(/können nicht abstimmen/)).toBeVisible();
  await expect(observer.p.getByRole('button', { name: 'Ja', exact: true })).toHaveCount(0);

  // 8. Ben is removed during the vote: his vote is refused and the page
  //    says so. Readmitted, it picks the meeting up again without a reload.
  const benInvite = inviteOf('ben@example.org').id;
  await api('post', `/api/meetings/${meeting.id}/invites/${benInvite}/remove/`, {});
  await ben.p.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(ben.p.getByText(/Dieser Link ist nicht \(mehr\) gültig/)).toBeVisible();
  await api('post', `/api/meetings/${meeting.id}/invites/${benInvite}/readmit/`);
  await ben.p.clock.fastForward(31000);
  await ben.p.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(ben.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  await expect(progress).toHaveText('1 von 2 haben abgestimmt');

  for (const c of [anna, ben, observer]) await c.context.close();
});
