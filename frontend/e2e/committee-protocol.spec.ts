/** Committee protocol, seal and test run (Gremien-Raum, part 3): a secret
 *  vote with a finding and a repeated vote through to the printable protocol
 *  and the seal check, and a test run that leaves no trace.
 *
 *  Setup goes through the API as `demo`; rooms are titled "E2E …" and
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

type Api = (method: 'get' | 'post', path: string, data?: unknown) => Promise<any>;

/** Room with two voting groups (Anna, Ben) and a meeting far in the future. */
async function setup(page: Page, trackRoom: (id: number | string) => void, title: string, kinds: string[]) {
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const api: Api = async (method, path, data) => {
    const response = await page.request[method](`${API_BASE_URL}${path}`, { headers, data });
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : response.json();
  };
  const room = await api('post', '/api/rooms/', { title, kind: 'committee' });
  trackRoom(room.id);
  const templates = await api('get', '/api/committee-templates/');
  await api('post', '/api/committee-groups/apply-template/', { room: room.id, template: templates[0].id });
  const groups = await api('get', `/api/committee-groups/?room=${room.id}`);
  const voters = groups.filter((g: { is_observer: boolean }) => !g.is_observer);
  await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: voters[0].id, role: 'voting', text: 'Anna Muster <anna@example.org>',
  });
  await api('post', '/api/committee-members/bulk/', {
    room: room.id, group: voters[1].id, role: 'voting', text: 'Ben Beispiel <ben@example.org>',
  });
  const meeting = await api('post', '/api/question-sets/', {
    room: room.id, type: 'meeting', title: 'E2E Sitzung', scheduled_at: '2030-01-15T10:00:00Z',
  });
  for (const text of kinds) {
    await api('post', '/api/questions/', {
      question_set: meeting.id, kind: 'resolution', text: { de: text },
    });
  }
  await api('post', `/api/meetings/${meeting.id}/invites/`);
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  const linkOf = (email: string): string =>
    summary.invites.find((i: { member: { email: string } }) => i.member.email === email).url;
  return { api, room, meeting, linkOf };
}

test('protocol and seal: finding, repeated vote, verification', async ({ page, browser, trackRoom }) => {
  await login(page);
  const { api, room, meeting, linkOf } = await setup(page, trackRoom, 'E2E Gremium Protokoll', [
    'Der Haushalt wird genehmigt.',
    'Die Satzung wird geändert.',
  ]);
  await api('post', `/api/meetings/${meeting.id}/start/`);

  const open = async (email: string) => {
    const context = await browser.newContext({ locale: 'de-DE' });
    const p = await context.newPage();
    await p.goto(linkOf(email));
    await expect(p.getByText('Bitte warten Sie auf die nächste Abstimmung.')).toBeVisible();
    return { context, p };
  };
  const anna = await open('anna@example.org');
  const ben = await open('ben@example.org');
  const voteYes = async (m: { p: Page }) => {
    await m.p.getByRole('button', { name: 'Ja', exact: true }).click();
    await expect(m.p.getByText('Ihre Stimme ist abgegeben.')).toBeVisible();
  };

  // 1. Item 1: both vote yes, the chair closes and sets the finding.
  await page.goto(`/sets/${meeting.id}/meeting`);
  const first = page.getByTestId('console-item').first();
  const second = page.getByTestId('console-item').nth(1);
  await first.getByRole('button', { name: /Haushalt wird genehmigt/ }).click();
  await first.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await expect(page.getByTestId('beamer-progress')).toHaveText('0 von 2 haben abgestimmt');
  await voteYes(anna);
  // Ben is the last voter: the vote closes automatically.
  await ben.p.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(page.getByTestId('beamer-result')).toBeVisible();
  await expect(page.getByTestId('beamer-finding')).toHaveCount(0);
  await first.getByRole('group', { name: 'Feststellung' }).getByRole('button', { name: 'Angenommen' }).click();
  await expect(page.getByTestId('beamer-finding')).toHaveText('Angenommen');

  // 2. Item 2: vote, close, reset with a comment, vote again, close.
  await second.getByRole('button', { name: /Satzung wird geändert/ }).click();
  await second.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await voteYes(anna);
  await second.getByRole('button', { name: 'Abstimmung schließen' }).click();
  await second.getByRole('button', { name: 'Abstimmung zurücksetzen …' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Kommentar (Pflicht)').fill('Technischer Fehler');
  await dialog.getByRole('button', { name: 'Zurücksetzen' }).click();
  await expect(dialog).toHaveCount(0);
  await second.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await expect(anna.p.getByRole('button', { name: 'Ja', exact: true })).toBeVisible();
  await voteYes(anna);
  await ben.p.getByRole('button', { name: 'Ja', exact: true }).click();
  await expect(page.getByTestId('beamer-result')).toBeVisible();

  // 3. End the meeting; the room overview links to the protocol.
  await api('post', `/api/meetings/${meeting.id}/end/`);
  await page.goto(`/rooms/${room.id}`);
  await page.getByRole('link', { name: 'Protokoll von E2E Sitzung' }).click();
  await page.waitForURL(/\/sets\/\d+\/protocol$/);

  // 4. The protocol: result per group, finding, repeat note, seal data.
  await expect(page.getByTestId('protocol')).toBeVisible();
  const items = page.getByTestId('protocol-item');
  await expect(items).toHaveCount(2);
  const item1 = items.nth(0);
  await expect(item1).toContainText('Haushalt wird genehmigt');
  await expect(item1).toContainText('Feststellung: angenommen');
  await expect(item1).toContainText('2 von 2 Stimmberechtigten haben abgestimmt');
  await expect(item1.getByText(/\(1\/1\): Ja 1/)).toHaveCount(2);
  await expect(items.nth(1)).toContainText('Abstimmung wiederholt (Durchgang 1): Technischer Fehler');
  const reference = (await item1.locator('a.font-mono').innerText()).trim();
  expect(reference).not.toBe('');
  const fingerprintText = await item1.getByText(/^Fingerabdruck:/).innerText();
  const fingerprint = fingerprintText.replace(/^Fingerabdruck:\s*/, '').replace(/\s+/g, '');
  expect(fingerprint).toMatch(/^[0-9a-f]{64}$/);

  // 4b. The PDF download: served as a PDF, and the link triggers a download.
  const pdfLink = page.getByTestId('protocol-pdf');
  const href = (await pdfLink.getAttribute('href'))!;
  expect(href).toContain('lang=de');
  const pdf = await page.request.get(href);
  expect(pdf.headers()['content-type']).toContain('application/pdf');
  expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
  const [download] = await Promise.all([page.waitForEvent('download'), pdfLink.click()]);
  expect(download.suggestedFilename()).toMatch(/^Protokoll-/);

  // 5. The seal check, via the room's check page.
  await page.goto(`/rooms/${room.id}/seals`);
  await page.getByLabel('Kennung', { exact: true }).fill(reference);
  await page.getByLabel('Fingerabdruck (optional)').fill(fingerprint.slice(0, 16));
  await page.getByRole('button', { name: 'Prüfen', exact: true }).click();
  await expect(page.getByText('Stimmt mit dem Siegel überein.').first()).toBeVisible();
  await expect(page.getByText('Der Fingerabdruck stimmt überein.')).toBeVisible();
  await expect(page.getByText('Kette intakt.')).toBeVisible();

  for (const c of [anna, ben]) await c.context.close();
});

test('test run leaves no trace', async ({ page, browser, trackRoom }) => {
  await login(page);
  const { api, meeting, linkOf } = await setup(page, trackRoom, 'E2E Gremium Testlauf', [
    'Der Antrag wird angenommen.',
  ]);
  const anna = await browser.newContext({ locale: 'de-DE' });
  const annaPage = await anna.newPage();
  await annaPage.goto(linkOf('anna@example.org'));

  // 1. Far from the scheduled date, starting offers a test run.
  await page.goto(`/sets/${meeting.id}`);
  await page.getByRole('button', { name: 'Sitzung beginnen' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Die Sitzung ist für');
  const consoleTab = page.context().waitForEvent('page');
  await dialog.getByRole('button', { name: 'Testlauf starten' }).click();
  const consolePage = await consoleTab;
  await expect(consolePage).toHaveURL(/\/sets\/\d+\/meeting$/);
  await expect(consolePage.getByTestId('trial-banner')).toHaveText('Testlauf – nichts wird protokolliert.');

  // 2. One vote in the test run.
  const item = consolePage.getByTestId('console-item').first();
  await item.getByRole('button', { name: /Antrag wird angenommen/ }).click();
  await item.getByRole('button', { name: 'Abstimmung öffnen' }).click();
  await annaPage.reload();
  await annaPage.getByRole('button', { name: 'Ja', exact: true }).click();
  // The only voter closes the vote automatically.
  await expect(consolePage.getByTestId('beamer-result')).toBeVisible();
  // A test run records no findings.
  await expect(item.getByRole('group', { name: 'Feststellung' })).toHaveCount(0);
  await consolePage.close();

  // 3. Ending the test run resets the meeting to "Planned".
  await page.getByRole('button', { name: 'Testlauf beenden' }).click();
  await expect(page.getByRole('dialog')).toContainText('auf den Stand vor dem Testlauf zurückgesetzt');
  await page.getByRole('dialog').getByRole('button', { name: 'Testlauf beenden' }).click();
  await expect(page.getByRole('button', { name: 'Sitzung beginnen' })).toBeVisible();
  await expect(page.getByText('Geplant', { exact: true }).first()).toBeVisible();
  const summary = await api('get', `/api/meetings/${meeting.id}/`);
  expect(summary.trial).toBeFalsy();

  // 4. A normal start works afterwards.
  await page.getByRole('button', { name: 'Sitzung beginnen' }).click();
  const normalTab = page.context().waitForEvent('page');
  await page.getByRole('dialog').getByRole('button', { name: 'Jetzt beginnen' }).click();
  const normalConsole = await normalTab;
  await expect(normalConsole.getByTestId('trial-banner')).toHaveCount(0);
  await normalConsole.close();
  await expect(page.getByRole('button', { name: 'Sitzung beenden' })).toBeVisible();

  await anna.close();
});
