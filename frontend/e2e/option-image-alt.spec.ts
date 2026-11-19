/** Alt text for answer-option images (#342): the option image dialog asks for
 *  the description (optionally with an AI suggestion), an "Edit image" button
 *  reopens it, an image-only option without a description shows a
 *  non-blocking hint, and the participant page names an image-only choice by
 *  its description. Runs as `demo`; seeds its own "E2E Option alt" rooms and
 *  deletes them. No real AI calls (the suggestion is stubbed). */
import type { Page } from '@playwright/test';
import { test, expect, API_BASE_URL, csrfToken } from './fixtures';
import { apiClient, control, createRoomWithQuestions, startRun } from './helpers/seed';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5174';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 860 } });

// 1x1 PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==',
  'base64',
);
const FILE = { name: 'hund.png', mimeType: 'image/png', buffer: PNG };
const ALT_LABEL = 'Bildbeschreibung (Alternativtext)';

// Native browser dialogs (prompt/alert/confirm) must never show up.
let nativeDialogs = 0;

async function signIn(page: Page, aiVision: boolean) {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) Object.assign(json, { onboarding_tour_seen: true, ai_vision_enabled: aiVision });
    await route.fulfill({ response, json });
  });
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL(`${BASE_URL}/**`);
}

test.beforeEach(async ({ page }) => {
  nativeDialogs = 0;
  page.on('dialog', (dialog) => {
    nativeDialogs += 1;
    void dialog.dismiss();
  });
});

test.afterEach(() => {
  expect(nativeDialogs, 'no native browser dialog').toBe(0);
});

async function uploadImage(page: Page) {
  const token = await csrfToken(page.request);
  const up = await page.request.post(`${API_BASE_URL}/api/images/`, {
    headers: token ? { 'X-CSRFToken': token } : undefined,
    multipart: { file: FILE },
  });
  expect(up.ok(), await up.text()).toBeTruthy();
  return (await up.json()) as { id: number; url: string };
}

type Opt = { text: { de: string; en: string }; is_correct?: boolean; image?: string; image_alt?: { de: string; en: string } };

/** A single-choice question with `options`; opens its editor. */
async function openQuestion(page: Page, trackRoom: (id: number) => void, options?: Opt[]) {
  const room = await createRoomWithQuestions(page.request, [], 'Option alt', trackRoom, 'E2E Option alt');
  const q = await apiClient(page.request).post('/api/questions/', {
    question_set: room.setId,
    kind: 'single_choice',
    text: { de: '<p>Welches Tier?</p>', en: '' },
    options: (options ?? [
      { text: { de: 'Ja', en: 'Yes' } },
      { text: { de: 'Nein', en: 'No' } },
    ]).map((o) => ({ is_correct: false, ...o })),
  });
  await page.goto(`/sets/${room.setId}/questions/${q.id}`);
  return { setId: room.setId as number, code: room.code as string, id: q.id as number };
}

async function saveQuestion(page: Page, id: number) {
  const saved = page.waitForResponse(
    (r) => r.url().includes(`/api/questions/${id}/`) && r.request().method() !== 'GET',
  );
  await page.getByRole('button', { name: 'Speichern', exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  return apiClient(page.request).get(`/api/questions/${id}/`);
}

test.describe('without AI vision', () => {
  test.beforeEach(async ({ page }) => signIn(page, false));

  test('upload option image asks for alt and saves it', async ({ page, trackRoom }) => {
    const q = await openQuestion(page, trackRoom);
    await page.getByTitle('Bild hinzufügen').first().locator('input[type="file"]').setInputFiles(FILE);
    const dialog = page.getByRole('dialog', { name: 'Bild einfügen' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel(ALT_LABEL).fill('Ein brauner Hund');
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(dialog).toBeHidden();
    const saved = await saveQuestion(page, q.id);
    expect(saved.options[0].image).toBeTruthy();
    expect(saved.options[0].image_alt.de).toBe('Ein brauner Hund');
  });

  test('edit button reopens dialog prefilled', async ({ page, trackRoom }) => {
    const { url } = await uploadImage(page);
    const q = await openQuestion(page, trackRoom, [
      { text: { de: 'Hund', en: 'Dog' }, image: url, image_alt: { de: 'Alt vorher', en: '' } },
      { text: { de: 'Katze', en: 'Cat' } },
    ]);
    await page.getByRole('button', { name: 'Bild bearbeiten' }).click();
    const dialog = page.getByRole('dialog', { name: 'Bild bearbeiten' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel(ALT_LABEL)).toHaveValue('Alt vorher');
    // The saved image's credit fields come along.
    await expect(dialog.getByLabel('Urheber:in')).toBeVisible();
    await dialog.getByLabel(ALT_LABEL).fill('egal');
    await dialog.getByRole('button', { name: 'Abbrechen' }).click();
    await expect(dialog).toBeHidden();

    await page.getByRole('button', { name: 'Bild bearbeiten' }).click();
    await expect(dialog.getByLabel(ALT_LABEL)).toHaveValue('Alt vorher');
    await dialog.getByLabel(ALT_LABEL).fill('Alt nachher');
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(dialog).toBeHidden();
    const saved = await saveQuestion(page, q.id);
    expect(saved.options[0].image_alt).toEqual({ de: 'Alt nachher', en: '' });
  });

  test('image-only option without alt shows hint; hint disappears after alt', async ({ page, trackRoom }) => {
    const { url } = await uploadImage(page);
    const q = await openQuestion(page, trackRoom, [
      { text: { de: '', en: '' }, image: url },
      { text: { de: 'Katze', en: 'Cat' }, image: url },
    ]);
    // Only the image-only option is flagged (the other one has text).
    const hint = page.getByRole('button', { name: 'Bildbeschreibung fehlt' });
    await expect(hint).toHaveCount(1);
    // Never blocks saving (Save returns to the set page).
    await saveQuestion(page, q.id);
    await page.goto(`/sets/${q.setId}/questions/${q.id}`);
    await expect(hint).toHaveCount(1);

    await hint.click();
    const dialog = page.getByRole('dialog', { name: 'Bild bearbeiten' });
    await dialog.getByLabel(ALT_LABEL).fill('Ein Hund');
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(dialog).toBeHidden();
    await expect(hint).toHaveCount(0);
    const saved = await saveQuestion(page, q.id);
    expect(saved.options[0].image_alt.de).toBe('Ein Hund');
  });

  test('participant page: image-only option button has accessible name = alt; option with text has img alt=""', async ({
    page,
    browser,
    trackRoom,
  }) => {
    const { url } = await uploadImage(page);
    const q = await openQuestion(page, trackRoom, [
      { text: { de: '', en: '' }, image: url, image_alt: { de: 'Ein Hund', en: '' } },
      { text: { de: 'Katze', en: 'Cat' }, image: url, image_alt: { de: 'Eine Katze', en: '' } },
    ]);
    const api = apiClient(page.request);
    const runId = await startRun(api, q.setId);
    const ctx = await browser.newContext({ locale: 'de-DE' });
    const p = await ctx.newPage();
    try {
      await p.goto(`${API_BASE_URL}/p/${q.code}/`);
      await control(api, runId, 'open', q.id);
      const options = p.locator('#options');
      await expect(options.getByRole('button', { name: 'Ein Hund' })).toBeVisible();
      const withText = options.getByRole('button', { name: 'Katze' });
      await expect(withText).toBeVisible();
      await expect(withText.locator('img')).toHaveAttribute('alt', '');
    } finally {
      await ctx.close();
    }
  });
});

test.describe('with AI vision', () => {
  test.beforeEach(async ({ page }) => signIn(page, true));

  test('suggest for option image', async ({ page, trackRoom }) => {
    let body: unknown = null;
    await page.route(/\/api\/images\/\d+\/alt-suggestion\/$/, async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { alt: 'Hund auf einer Wiese' } });
    });
    const q = await openQuestion(page, trackRoom);
    await page.getByTitle('Bild hinzufügen').first().locator('input[type="file"]').setInputFiles(FILE);
    const dialog = page.getByRole('dialog', { name: 'Bild einfügen' });
    await dialog.getByRole('button', { name: 'Vorschlag erstellen' }).click();
    await expect(dialog.getByLabel(ALT_LABEL)).toHaveValue('Hund auf einer Wiese');
    expect(body).toEqual({ lang: 'de' });
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(dialog).toBeHidden();
    const saved = await saveQuestion(page, q.id);
    expect(saved.options[0].image_alt.de).toBe('Hund auf einer Wiese');
  });
});
