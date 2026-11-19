/** "Fragen übernehmen" (#323): paste questions in the simple text format or
 *  GIFT, review them like AI proposals, take over a selection. The button is
 *  core authoring — offered in easy mode and without AI, so whoami is stubbed
 *  to `easy_mode: true, ai_enabled: false`. Only an "E2E Import" room is
 *  seeded and deleted. */
import { test, expect, API_BASE_URL } from './fixtures';
import { createRoomWithQuestions } from './helpers/seed';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5174';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 1000 } });

test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) Object.assign(json, { onboarding_tour_seen: true, easy_mode: true, ai_enabled: false });
    await route.fulfill({ response, json });
  });
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL(`${BASE_URL}/**`);
});

const SIMPLE_TEXT = `F: Welche Farbe hat der Himmel?
* Blau
- Grün
- Rot

F: Die Erde ist rund.
* Richtig
- Falsch

F: Erklären Sie kurz die Photosynthese.
L: Pflanzen wandeln Lichtenergie in chemische Energie um.
`;

const GIFT_TEXT = `::Tiere:: Ordnen Sie die Laute zu. {
=Hund -> bellt
=Katze -> miaut
=Kuh -> muht
}

::Primzahlen:: Welche Zahlen sind Primzahlen? {
~%50%2
~%50%3
~%-100%4
}
`;

async function openImport(page: import('@playwright/test').Page, setId: number) {
  await page.goto(`/sets/${setId}`);
  await page.getByRole('button', { name: 'Fragen übernehmen' }).first().click();
}

test('pasted simple text → review → two questions taken over, AI scoring off', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Import', trackRoom, 'E2E Import');
  await openImport(page, room.setId);

  await page.getByRole('textbox', { name: 'Text einfügen' }).fill(SIMPLE_TEXT);
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();

  await expect(page.getByText('Übernommene Fragen prüfen')).toBeVisible();
  await expect(page.getByText('Erkannt: Einfaches Textformat · 3 Fragen')).toBeVisible();
  // No AI wording in the review of an import.
  await expect(page.getByText(/KI/)).toHaveCount(0);

  // The detected format is stored with the job: still shown after a reload,
  // when the review is reopened from the set's hint.
  await page.reload();
  await expect(page.getByText('Übernommene Fragen warten auf Ihre Prüfung.')).toBeVisible();
  await page.getByRole('button', { name: 'Prüfen', exact: true }).click();
  await expect(page.getByText('Erkannt: Einfaches Textformat · 3 Fragen')).toBeVisible();

  await page.getByRole('checkbox', { name: /Welche Farbe hat der Himmel/ }).check();
  await page.getByRole('checkbox', { name: /Photosynthese/ }).check();
  await page.getByRole('button', { name: /Ausgewählte übernehmen/ }).click();
  await expect(page.getByText('Übernommene Fragen prüfen')).toHaveCount(0);

  const response = await page.request.get(`${API_BASE_URL}/api/questions/?question_set=${room.setId}`);
  const questions = (await response.json()).results as {
    kind: string;
    text: unknown;
    ai_evaluate: boolean;
    model_solution: string;
  }[];
  expect(questions).toHaveLength(2);
  // Stored as editor HTML, not double-escaped.
  const choice = questions.find((q) => q.kind === 'single_choice');
  expect(JSON.stringify(choice?.text)).toContain('<p>Welche Farbe hat der Himmel?</p>');
  const openText = questions.find((q) => q.kind === 'open_text');
  expect(openText?.model_solution).toContain('Lichtenergie');
  expect(openText?.ai_evaluate).toBe(false);
  await expect(page.getByText('Welche Farbe hat der Himmel?')).toBeVisible();
});

test('GIFT matching question is skipped and reported', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Import GIFT', trackRoom, 'E2E Import');
  await openImport(page, room.setId);

  await page.getByRole('textbox', { name: 'Text einfügen' }).fill(GIFT_TEXT);
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();

  await expect(page.getByText('Erkannt: GIFT (Moodle) · 1 Frage')).toBeVisible();
  await expect(page.getByText('1 übersprungen: Zuordnung (nicht unterstützt)')).toBeVisible();
  await page.getByRole('button', { name: 'Verwerfen', exact: true }).click();
  await expect(page.getByText('Übernommene Fragen prüfen')).toHaveCount(0);
});
