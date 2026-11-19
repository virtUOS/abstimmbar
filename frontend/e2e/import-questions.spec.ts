/** "Fragen übernehmen" (#323): paste questions in the simple text format or
 *  GIFT, review them like AI proposals, take over a selection. The button is
 *  core authoring — offered in easy mode and without AI, so whoami is stubbed
 *  to `easy_mode: true, ai_enabled: false`. Only an "E2E Import" room is
 *  seeded and deleted. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
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
  // Scoped to the page: an import running in a parallel test can show the
  // app-wide status bar with its own "Prüfen" button.
  await page.getByRole('main').getByRole('button', { name: 'Prüfen', exact: true }).click();
  await expect(page.getByText('Erkannt: Einfaches Textformat · 3 Fragen')).toBeVisible();

  await page.getByRole('checkbox', { name: /Welche Farbe hat der Himmel/ }).check();
  await page.getByRole('checkbox', { name: /Photosynthese/ }).check();
  await page.getByRole('button', { name: /Ausgewählte übernehmen/ }).click();
  await expect(page.getByText('Übernommene Fragen prüfen')).toHaveCount(0);
  // The third, unselected question stays for later review (#292).
  await expect(page.getByText('Übernommene Fragen warten auf Ihre Prüfung.')).toBeVisible();

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

test('uploaded GIFT file → review with skip notice', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Import Datei', trackRoom, 'E2E Import');
  await openImport(page, room.setId);

  await page.getByRole('button', { name: 'Datei hochladen', exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: 'moodle.gift',
    mimeType: 'text/plain',
    buffer: Buffer.from(GIFT_TEXT, 'utf-8'),
  });
  await expect(page.getByText('moodle.gift')).toBeVisible();
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();

  await expect(page.getByText('Übernommene Fragen prüfen')).toBeVisible();
  await expect(page.getByText('Erkannt: GIFT (Moodle) · 1 Frage')).toBeVisible();
  await expect(page.getByText('1 übersprungen: Zuordnung (nicht unterstützt)')).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /Welche Zahlen sind Primzahlen/ })).toBeVisible();
  await page.getByRole('button', { name: 'Verwerfen', exact: true }).click();
  await expect(page.getByText('Übernommene Fragen prüfen')).toHaveCount(0);
});

/** Self-made H5P MultiChoice with a 2×2 PNG, credited "Rotes Quadrat" by
 *  Karen Jackson, CC BY-ND 4.0 (shared with the backend tests). */
const H5P_IMAGE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../backend/rooms/test_fixtures/import/multichoice-image.h5p',
);

test('H5P with credited image → review shows image + credit → editor keeps the credit (#336)', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Import Bild', trackRoom, 'E2E Import');
  await openImport(page, room.setId);

  await page.getByRole('button', { name: 'Datei hochladen', exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: 'farbe.h5p',
    mimeType: 'application/zip',
    buffer: fs.readFileSync(H5P_IMAGE),
  });
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();

  await expect(page.getByText('Übernommene Fragen prüfen')).toBeVisible();
  const preview = page.getByRole('img', { name: 'Rote Fläche' });
  await expect(preview).toBeVisible();
  await expect(preview).toHaveAttribute('src', /\/media\/question-images\//);
  // The stored file actually loads.
  await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByTestId('image-credits')).toHaveText(
    'Bild: „Rotes Quadrat“ von Karen Jackson, CC BY-ND 4.0',
  );

  await page.getByRole('checkbox', { name: /Welche Farbe hat die Fläche/ }).check();
  await page.getByRole('button', { name: /Ausgewählte übernehmen/ }).click();
  await expect(page.getByText('Übernommene Fragen prüfen')).toHaveCount(0);

  const response = await page.request.get(`${API_BASE_URL}/api/questions/?question_set=${room.setId}`);
  const [question] = (await response.json()).results as { id: number }[];
  await page.goto(`/sets/${room.setId}/questions/${question.id}`);
  const section = page.getByTestId('image-credits-editor');
  await expect(section.getByRole('heading', { name: 'Bildnachweise' })).toBeVisible();
  await expect(section.getByLabel('Urheber:in')).toHaveValue('Karen Jackson');
  await expect(section.getByText('Kein Bildnachweis')).toHaveCount(0);
});

test('one rejected proposal does not stop the others from being taken over', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Import Teilfehler', trackRoom, 'E2E Import');
  await openImport(page, room.setId);
  await page.getByRole('textbox', { name: 'Text einfügen' }).fill(SIMPLE_TEXT);
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();
  await expect(page.getByText('Übernommene Fragen prüfen')).toBeVisible();

  // The first question POST is rejected by the server.
  let rejected = false;
  await page.route(/\/api\/questions\/$/, async (route) => {
    if (route.request().method() !== 'POST' || rejected) return route.continue();
    rejected = true;
    await route.fulfill({ status: 400, json: { options: ['Add at least two answer options, each with text.'] } });
  });
  await page.getByRole('checkbox', { name: /Welche Farbe hat der Himmel/ }).check();
  await page.getByRole('checkbox', { name: /Photosynthese/ }).check();
  await page.getByRole('button', { name: /Ausgewählte übernehmen/ }).click();

  await expect(page.getByText(/1 Frage konnte nicht übernommen werden\./)).toBeVisible();
  // The panel stays open; the rejected proposal is still there.
  await expect(page.getByRole('checkbox', { name: /Welche Farbe hat der Himmel/ })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /Photosynthese/ })).toHaveCount(0);
  const response = await page.request.get(`${API_BASE_URL}/api/questions/?question_set=${room.setId}`);
  const questions = (await response.json()).results as { kind: string }[];
  expect(questions.map((q) => q.kind)).toEqual(['open_text']);
});
