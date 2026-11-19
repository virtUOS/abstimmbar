/** "Insert image" dialog: after an upload in the rich-text question editor
 *  (and for answer-option images) the app's own dialog asks for the alt text
 *  and the image credit, optionally with an AI suggestion (AI_VISION).
 *  Runs as `demo`; seeds its own "E2E Image dialog" rooms and deletes them. */
import type { Page } from '@playwright/test';
import { test, expect, API_BASE_URL, csrfToken } from './fixtures';
import { apiClient, createRoomWithQuestions } from './helpers/seed';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5174';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 860 } });

// 1x1 PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==',
  'base64',
);
const FILE = { name: 'punkt.png', mimeType: 'image/png', buffer: PNG };

// Native browser dialogs (prompt/alert/confirm) must never show up.
let nativeDialogs = 0;

/** Signs in as demo; whoami is patched (tour seen, AI vision on/off). */
async function signIn(page: Page, aiVision: boolean, extra: Record<string, unknown> = {}) {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) Object.assign(json, { onboarding_tour_seen: true, ai_vision_enabled: aiVision, ...extra });
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

async function upload(page: Page, name = 'demo') {
  const token = await csrfToken(page.request);
  const up = await page.request.post(`${API_BASE_URL}/api/images/`, {
    headers: token ? { 'X-CSRFToken': token } : undefined,
    multipart: { file: { ...FILE, name: `${name}.png` } },
  });
  expect(up.ok(), await up.text()).toBeTruthy();
  return (await up.json()) as { id: number; url: string };
}

/** A question (single choice) whose German text is `html`; opens its editor. */
async function openQuestion(page: Page, trackRoom: (id: number) => void, html = '<p>Was sehen Sie?</p>') {
  const room = await createRoomWithQuestions(page.request, [], 'Image dialog', trackRoom, 'E2E Image dialog');
  const q = await apiClient(page.request).post('/api/questions/', {
    question_set: room.setId,
    kind: 'single_choice',
    text: { de: html, en: '' },
    options: [
      { text: { de: 'Ja', en: 'Yes' }, is_correct: true },
      { text: { de: 'Nein', en: 'No' }, is_correct: false },
    ],
  });
  await page.goto(`/sets/${room.setId}/questions/${q.id}`);
  return { setId: room.setId as number, id: q.id as number };
}

const editor = (page: Page) =>
  page.locator('[data-tour="question.lang-tabs"] [contenteditable="true"]').first();

async function uploadInEditor(page: Page) {
  await editor(page).click();
  await page.locator('[data-tour="question.lang-tabs"] input[type="file"]').first().setInputFiles(FILE);
  const dialog = page.getByRole('dialog', { name: 'Bild einfügen' });
  await expect(dialog).toBeVisible();
  return dialog;
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

  test('upload opens dialog and saves alt + credit', async ({ page, trackRoom }) => {
    const q = await openQuestion(page, trackRoom);
    const dialog = await uploadInEditor(page);
    await expect(dialog.getByText('Beschreibt das Bild für Menschen, die es nicht sehen können.')).toBeVisible();
    await dialog.getByLabel('Bildbeschreibung (Alternativtext)').fill('Ein roter Punkt');
    await dialog.getByLabel('Urheber:in').fill('Karen Jackson');
    await dialog.getByRole('combobox', { name: /^Lizenz/ }).selectOption('cc-by');
    const patched = page.waitForResponse(
      (r) => /\/api\/images\/\d+\/credit\/$/.test(r.url()) && r.request().method() === 'PATCH',
    );
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    expect((await patched).ok()).toBeTruthy();
    await expect(dialog).toBeHidden();
    await expect(editor(page).locator('img[alt="Ein roter Punkt"]')).toHaveCount(1);

    const saved = await saveQuestion(page, q.id);
    expect(saved.text.de).toContain('alt="Ein roter Punkt"');
    await page.goto(`/sets/${q.setId}/questions/${q.id}`);
    const section = page.getByTestId('image-credits-editor');
    await expect(section.getByRole('heading', { name: 'Bildnachweise' })).toBeVisible();
    await expect(section.getByLabel('Urheber:in')).toHaveValue('Karen Jackson');
    await expect(section.getByRole('combobox', { name: /^Lizenz/ })).toHaveValue('cc-by');
  });

  test('skip inserts image without alt', async ({ page, trackRoom }) => {
    await openQuestion(page, trackRoom);
    const dialog = await uploadInEditor(page);
    let patches = 0;
    page.on('request', (r) => {
      if (r.method() === 'PATCH' && r.url().includes('/credit/')) patches += 1;
    });
    await dialog.getByRole('button', { name: 'Überspringen' }).click();
    await expect(dialog).toBeHidden();
    const img = editor(page).locator('img');
    await expect(img).toHaveCount(1);
    expect(await img.getAttribute('alt')).toBeFalsy();
    expect(patches).toBe(0);
  });

  test('esc inserts image without alt', async ({ page, trackRoom }) => {
    await openQuestion(page, trackRoom);
    const dialog = await uploadInEditor(page);
    await dialog.getByLabel('Bildbeschreibung (Alternativtext)').fill('verworfen');
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    const img = editor(page).locator('img');
    await expect(img).toHaveCount(1);
    expect(await img.getAttribute('alt')).toBeFalsy();
    // The editor stays usable: a second upload opens a new dialog.
    const again = await uploadInEditor(page);
    await again.getByRole('button', { name: 'Überspringen' }).click();
    await expect(editor(page).locator('img')).toHaveCount(2);
  });

  test('edit button opens dialog prefilled', async ({ page, trackRoom }) => {
    const { id, url } = await upload(page, 'edit');
    const token = await csrfToken(page.request);
    const patch = await page.request.patch(`${API_BASE_URL}/api/images/${id}/credit/`, {
      headers: token ? { 'X-CSRFToken': token } : undefined,
      data: { author: 'Karen Jackson', license: 'cc-by-nd', version: '4.0' },
    });
    expect(patch.ok(), await patch.text()).toBeTruthy();
    // The image is in the saved question → its credit comes with it.
    const q = await openQuestion(
      page,
      trackRoom,
      `<p>Was sehen Sie?</p><p><img src="${url}" alt="Alt vorher"></p>`,
    );

    await editor(page).locator('img').click();
    await page.getByRole('button', { name: 'Bildbeschreibung', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Bild bearbeiten' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toHaveValue('Alt vorher');
    await expect(dialog.getByLabel('Urheber:in')).toHaveValue('Karen Jackson');
    await expect(dialog.getByRole('combobox', { name: /^Lizenz/ })).toHaveValue('cc-by-nd');

    // Cancel = no change.
    await dialog.getByLabel('Bildbeschreibung (Alternativtext)').fill('egal');
    await dialog.getByRole('button', { name: 'Abbrechen' }).click();
    await expect(dialog).toBeHidden();
    await expect(editor(page).locator('img[alt="Alt vorher"]')).toHaveCount(1);

    // The editor takes its focus back (and with it the old selection) a
    // frame after the dialog closed: click until the image is selected.
    await expect(async () => {
      await editor(page).locator('img').click();
      await expect(editor(page).locator('img.ProseMirror-selectednode')).toHaveCount(1, { timeout: 500 });
    }).toPass();
    await page.getByRole('button', { name: 'Bildbeschreibung', exact: true }).click();
    await dialog.getByLabel('Bildbeschreibung (Alternativtext)').fill('Alt nachher');
    await dialog.getByLabel('Urheber:in').fill('Karen J.');
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(dialog).toBeHidden();
    // The "Image credits" section follows at once.
    await expect(page.getByTestId('image-credits-editor').getByLabel('Urheber:in')).toHaveValue('Karen J.');
    const saved = await saveQuestion(page, q.id);
    expect(saved.text.de).toContain('alt="Alt nachher"');
  });

  test('image unknown to the page shows the alt text only', async ({ page, trackRoom }) => {
    const { url } = await upload(page, 'unknown');
    // E.g. pasted from another question: in the text, but not among the
    // question's image credits → no id for this src on the page.
    await openQuestion(page, trackRoom);
    await page.route(/\/api\/questions\/\d+\/$/, async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const response = await route.fetch();
      const json = await response.json();
      json.text = { de: `<p><img src="${url}" alt=""></p>`, en: '' };
      json.image_credits = [];
      await route.fulfill({ response, json });
    });
    await page.reload();
    await editor(page).locator('img').click();
    await page.getByRole('button', { name: 'Bildbeschreibung', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Bild bearbeiten' });
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toBeVisible();
    await expect(dialog.getByLabel('Urheber:in')).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Abbrechen' }).click();
    await expect(dialog).toBeHidden();
  });

  test('link uses in-app dialog', async ({ page, trackRoom }) => {
    await openQuestion(page, trackRoom);
    await editor(page).getByText('Was sehen Sie?').dblclick();
    await page.locator('[data-tour="question.lang-tabs"]').getByRole('button', { name: 'Link' }).click();
    const dialog = page.getByRole('dialog', { name: 'URL eingeben' });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('URL eingeben').fill('https://example.org/');
    await dialog.getByRole('button', { name: 'OK' }).click();
    await expect(dialog).toBeHidden();
    // afterEach: no native prompt() fired.
  });

  test('link from the in-app dialog is applied to the selection', async ({ page, trackRoom }) => {
    // @basicbar/ui 0.10.0 (unreleased): the text selection collapses to the
    // start when the URL dialog closes (Firefox and Chromium), so the link is
    // not applied. Remove once basicbar keeps the selection across the dialog.
    test.fail(true, 'basicbar link dialog loses the text selection');
    await openQuestion(page, trackRoom);
    await editor(page).getByText('Was sehen Sie?').dblclick();
    await page.locator('[data-tour="question.lang-tabs"]').getByRole('button', { name: 'Link' }).click();
    const dialog = page.getByRole('dialog', { name: 'URL eingeben' });
    await dialog.getByLabel('URL eingeben').fill('https://example.org/');
    await dialog.getByRole('button', { name: 'OK' }).click();
    await expect(editor(page).locator('a[href="https://example.org/"]')).toHaveCount(1);
  });

  test('suggest button hidden without AI_VISION', async ({ page, trackRoom }) => {
    await openQuestion(page, trackRoom);
    const dialog = await uploadInEditor(page);
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Vorschlag erstellen' })).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Überspringen' }).click();
  });

  test('option image upload opens the credit-only dialog', async ({ page, trackRoom }) => {
    await openQuestion(page, trackRoom);
    await page.getByTitle('Bild hinzufügen').first().locator('input[type="file"]').setInputFiles(FILE);
    const dialog = page.getByRole('dialog', { name: 'Bild einfügen' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toHaveCount(0);
    await dialog.getByLabel('Urheber:in').fill('Optionsfoto');
    const patched = page.waitForResponse(
      (r) => /\/api\/images\/\d+\/credit\/$/.test(r.url()) && r.request().method() === 'PATCH',
    );
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    const response = await patched;
    expect(response.ok()).toBeTruthy();
    expect((await response.json()).author).toBe('Optionsfoto');
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('img', { name: 'Antwortbild' })).toHaveCount(1);
  });
});

test.describe('with AI vision', () => {
  test.beforeEach(async ({ page }) => signIn(page, true));

  test('suggest fills alt field', async ({ page, trackRoom }) => {
    let body: unknown = null;
    await page.route(/\/api\/images\/\d+\/alt-suggestion\/$/, async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { alt: 'Roter Punkt auf weißem Grund' } });
    });
    await openQuestion(page, trackRoom);
    const dialog = await uploadInEditor(page);
    await dialog.getByRole('button', { name: 'Vorschlag erstellen' }).click();
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toHaveValue(
      'Roter Punkt auf weißem Grund',
    );
    expect(body).toEqual({ lang: 'de' });
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(editor(page).locator('img[alt="Roter Punkt auf weißem Grund"]')).toHaveCount(1);
  });

  test('suggest error shows message', async ({ page, trackRoom }) => {
    await page.route(/\/api\/images\/\d+\/alt-suggestion\/$/, (route) =>
      route.fulfill({ status: 502, json: { detail: 'Das KI-Modell kann keine Bilder lesen.' } }),
    );
    await openQuestion(page, trackRoom);
    const dialog = await uploadInEditor(page);
    await dialog.getByLabel('Bildbeschreibung (Alternativtext)').fill('Mein Entwurf');
    await dialog.getByRole('button', { name: 'Vorschlag erstellen' }).click();
    await expect(dialog.getByRole('alert')).toContainText('Das KI-Modell kann keine Bilder lesen.');
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toHaveValue('Mein Entwurf');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Überspringen' }).click();
  });

  test('read-only credit: alt editable, no credit inputs, no suggestion', async ({ page, trackRoom }) => {
    const { id, url } = await upload(page, 'foreign');
    const token = await csrfToken(page.request);
    const patch = await page.request.patch(`${API_BASE_URL}/api/images/${id}/credit/`, {
      headers: token ? { 'X-CSRFToken': token } : undefined,
      data: { author: 'Karen Jackson', license: 'cc-by-nd', version: '4.0' },
    });
    expect(patch.ok(), await patch.text()).toBeTruthy();
    // As if the image were also used in a room that isn't the user's.
    await page.route(/\/api\/questions\/\d+\/$/, async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const response = await route.fetch();
      const json = await response.json();
      for (const c of json.image_credits ?? []) c.editable = false;
      await route.fulfill({ response, json });
    });
    await openQuestion(page, trackRoom, `<p>Was sehen Sie?</p><p><img src="${url}" alt="Alt vorher"></p>`);
    let patches = 0;
    page.on('request', (r) => {
      if (r.method() === 'PATCH' && r.url().includes('/credit/')) patches += 1;
    });
    await editor(page).locator('img').click();
    await page.getByRole('button', { name: 'Bildbeschreibung', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Bild bearbeiten' });
    await expect(dialog.getByText(/Karen Jackson/)).toBeVisible();
    await expect(dialog.getByLabel('Urheber:in')).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: 'Vorschlag erstellen' })).toHaveCount(0);
    await dialog.getByLabel('Bildbeschreibung (Alternativtext)').fill('Alt neu');
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(dialog).toBeHidden();
    await expect(editor(page).locator('img[alt="Alt neu"]')).toHaveCount(1);
    expect(patches).toBe(0);
  });
});

test.describe('expert mode with AI vision', () => {
  test.beforeEach(async ({ page }) => signIn(page, true, { easy_mode: false }));

  test('suggestion uses the language of the edited tab', async ({ page, trackRoom }) => {
    let body: unknown = null;
    await page.route(/\/api\/images\/\d+\/alt-suggestion\/$/, async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { alt: 'Red dot on white' } });
    });
    await openQuestion(page, trackRoom);
    const tabs = page.locator('[data-tour="question.lang-tabs"]');
    await tabs.getByRole('tab', { name: /^en/ }).click();
    const dialog = await uploadInEditor(page);
    await expect(page.getByRole('dialog', { name: 'Bild einfügen' })).toHaveCount(1);
    await dialog.getByRole('button', { name: 'Vorschlag erstellen' }).click();
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toHaveValue('Red dot on white');
    await expect(dialog.getByLabel('Bildbeschreibung (Alternativtext)')).toHaveAttribute('lang', 'en');
    expect(body).toEqual({ lang: 'en' });
    await dialog.getByRole('button', { name: 'Übernehmen' }).click();
    await expect(editor(page).locator('img[alt="Red dot on white"]')).toHaveCount(1);
  });
});
