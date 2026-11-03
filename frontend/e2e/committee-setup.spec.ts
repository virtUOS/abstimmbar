/** Committee room setup (Gremien-Raum, part 1): create a committee room from
 *  a template, add members and a deputy, create a meeting, substitute a
 *  member, generate the personal links and follow one link through the
 *  meeting's lifecycle on the entry page.
 *
 *  Runs as `demo`; the room is titled "E2E …" and deleted afterwards. The
 *  expert/simple mode is answered in the browser via the `/api/whoami/`
 *  response, so the account's stored mode is never changed. */
import { test, expect, API_BASE_URL, csrfToken } from './fixtures';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 900 } });

/** Log in as demo with a fixed UI mode (not persisted). */
async function loginAs(
  page: import('@playwright/test').Page,
  easyMode: boolean,
): Promise<void> {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) {
      json.onboarding_tour_seen = true;
      json.easy_mode = easyMode;
    }
    await route.fulfill({ response, json });
  });
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL('http://localhost:5174/**');
}

test('committee room: groups, members, meeting links', async ({ page, browser, trackRoom }) => {
  await loginAs(page, false);

  // 1. Create the committee room (expert mode) and apply the template.
  await page.goto('/');
  await page.getByRole('button', { name: /Neuer Raum/ }).click();
  await page.getByRole('menuitem', { name: /^Gremien-Raum/ }).click();
  await expect(page.getByRole('heading', { name: 'Neuer Gremien-Raum' })).toBeVisible();
  await page.getByRole('textbox', { name: /^Name|Titel/ }).first().fill('E2E Gremium');
  await page.getByRole('button', { name: 'Anlegen' }).click();
  await page.waitForURL(/\/rooms\/\d+$/);
  const roomUrl = page.url();
  trackRoom(roomUrl.split('/').pop()!);
  // Committee rooms show no join code; members use personal links.
  await expect(page.getByText('Mitglieder treten über persönliche Links bei.')).toBeVisible();

  // The room-type filter on the overview finds it under "Gremien".
  await page.goto('/');
  await page.getByRole('radio', { name: 'Gremien' }).click();
  await expect(page.getByRole('link', { name: /E2E Gremium/ }).first()).toBeVisible();
  await page.goto(roomUrl);

  await page
    .getByRole('button', { name: 'Vorlage Professor*innen / Andere übernehmen' })
    .click();
  const panel = page.locator('section', { hasText: 'Gruppen und Mitglieder' }).first();
  for (const name of ['Professor*innen', 'Andere', 'Beobachtende']) {
    await expect(panel.getByRole('heading', { name })).toBeVisible();
  }

  const bulk = page.locator('form', { has: page.getByRole('heading', { name: 'Mitglieder hinzufügen' }) });
  // Group and role come first, then search or list as alternatives.
  const groupTop = (await bulk.getByLabel('Gruppe').boundingBox())!.y;
  const searchTop = (await bulk.getByLabel('Name oder E-Mail-Adresse').boundingBox())!.y;
  expect(groupTop).toBeLessThan(searchTop);
  await expect(bulk.getByLabel('E-Mail-Liste')).toHaveCount(0);

  // Search finds a member of another of my committee rooms and adds them.
  const headers = { 'X-CSRFToken': (await csrfToken(page.request)) ?? '' };
  const other = await (await page.request.post(`${API_BASE_URL}/api/rooms/`, {
    headers, data: { title: 'E2E Gremium Zwei', kind: 'committee' },
  })).json();
  trackRoom(other.id);
  const otherGroups = await (await page.request.get(
    `${API_BASE_URL}/api/committee-groups/?room=${other.id}`,
  )).json();
  await page.request.post(`${API_BASE_URL}/api/committee-members/bulk/`, {
    headers,
    data: { room: other.id, group: otherGroups[0].id, role: 'voting', text: 'Zora Bekannt <zora@example.org>' },
  });
  await bulk.getByLabel('Name oder E-Mail-Adresse').fill('zora');
  await bulk.getByRole('button', { name: /Zora Bekannt/ }).click();
  await expect(bulk.getByRole('status')).toContainText('1 angelegt, 0 übersprungen');
  await expect(panel.getByText('zora@example.org')).toBeVisible();

  // 2. Bulk-add members to "Andere"; the malformed entry is skipped.
  await bulk.getByRole('radio', { name: /E-Mail-Liste/ }).click();
  await bulk.getByLabel('Gruppe').selectOption({ label: 'Andere' });
  await bulk.getByLabel('E-Mail-Liste').fill('Anna Muster <anna@example.org>, bert@example.org; kaputt');
  await bulk.getByRole('button', { name: 'Mitglieder hinzufügen' }).click();
  await expect(bulk.getByRole('status')).toContainText('2 angelegt, 1 übersprungen');

  // 3. A deputy for "Andere".
  await bulk.getByLabel('Rolle').selectOption({ label: 'Stellvertretung' });
  await bulk.getByLabel('E-Mail-Liste').fill('vera@example.org');
  await bulk.getByRole('button', { name: 'Mitglieder hinzufügen' }).click();
  await expect(bulk.getByRole('status')).toContainText('1 angelegt, 0 übersprungen');

  // With members, the panel starts collapsed and shows a summary.
  await page.reload();
  const toggle = page.getByRole('button', { name: /Gruppen und Mitglieder/ });
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toContainText('Gruppen: 2 · Mitglieder: 4');
  await toggle.click();
  await expect(bulk).toBeVisible();

  // 4. A meeting with a date.
  await page.getByRole('button', { name: '+ Neue Sitzung' }).click();
  await page.getByPlaceholder(/Fakultätsrat/).fill('E2E Sitzung');
  // Full hours only: a date field plus an hour select.
  await page.getByLabel('Datum', { exact: true }).fill('2030-01-15');
  await expect(page.getByLabel('Uhrzeit').locator('option[value="10:15"]')).toHaveCount(0);
  await page.getByLabel('Uhrzeit').selectOption('10:00');
  await page.getByRole('button', { name: 'Speichern' }).click();
  await page.waitForURL(/\/sets\/\d+$/);

  // Links first: Anna's row survives the substitution below (status
  // "substituted"); the deputy only gets a link once substituting.
  await page.getByRole('button', { name: 'Links erzeugen' }).click();

  // Substitution: the suggested deputy for Anna is Vera.
  await page.getByLabel('Abwesendes Mitglied').selectOption({ label: 'Anna Muster' });
  const deputySelect = page.getByRole('combobox', { name: /^Stellvertretung/ });
  await expect(deputySelect).toHaveValue(/\d+/);
  await expect(deputySelect.locator('option:checked')).toHaveText(/vera/i);
  await page.getByRole('button', { name: 'Vertretung eintragen' }).click();
  await expect(page.getByTestId('substitution')).toContainText('vera');

  // 5. Generate again (never deletes): Anna is substituted, Vera has a link.
  await page.getByRole('button', { name: 'Links erzeugen' }).click();
  const rows = page.getByTestId('invite-row');
  const anna = rows.filter({ hasText: 'Anna Muster' });
  await expect(anna).toContainText('vertreten');
  const vera = rows.filter({ hasText: 'vera@example.org' });
  await expect(vera).toHaveCount(1);
  const invitesResponse = await page.request.get(
    `${API_BASE_URL}/api/meetings/${page.url().split('/').pop()}/`,
  );
  const summary = await invitesResponse.json();
  const veraInvite = summary.invites.find(
    (invite: { member: { email: string } }) => invite.member.email === 'vera@example.org',
  );
  expect(veraInvite.url).toBeTruthy();

  // Vera's link, in a fresh anonymous context: not started yet.
  const guest = await browser.newContext({ locale: 'de-DE' });
  const entry = await guest.newPage();
  await entry.goto(veraInvite.url);
  await expect(entry.getByText('Die Sitzung hat noch nicht begonnen')).toBeVisible();

  await page.getByRole('button', { name: 'Sitzung beginnen' }).click();
  // The badge is always shown; wait for the started state's end button.
  await expect(page.getByRole('button', { name: 'Sitzung beenden' })).toBeVisible();
  await entry.reload();
  await expect(entry.getByText('Die Sitzung läuft')).toBeVisible();

  // 6. End the meeting: the link becomes invalid.
  await page.getByRole('button', { name: 'Sitzung beenden' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Sitzung beenden' }).click();
  await expect(page.getByRole('button', { name: 'Sitzung beenden' })).toHaveCount(0);
  await entry.reload();
  await expect(entry.getByText('Dieser Link ist nicht (mehr) gültig')).toBeVisible();
  await guest.close();
});

test('simple mode offers no committee room', async ({ page }) => {
  await loginAs(page, true);
  await page.goto('/');
  // One kind only: a plain button that opens the form directly, no menu.
  await page.getByRole('button', { name: /Neuer Raum/ }).click();
  await expect(page.getByRole('heading', { name: 'Neuer Raum' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: /Gremien-Raum/ })).toHaveCount(0);
});
