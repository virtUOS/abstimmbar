/** Image credits (#336) on the presenter: one muted line under the question
 *  for credited images that are actually visible; none in the wide
 *  mindmap/matrix layout where question images are hidden.
 *  Runs as `demo`; seeds its own "E2E Credits" rooms and deletes them. */
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

test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) json.onboarding_tour_seen = true;
    await route.fulfill({ response, json });
  });
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL(`${BASE_URL}/**`);
});

/** Upload an image and give it the Karen Jackson credit; returns its /media/ URL. */
async function creditedImage(page: Page): Promise<string> {
  const token = await csrfToken(page.request);
  const headers = token ? { 'X-CSRFToken': token } : undefined;
  const up = await page.request.post(`${API_BASE_URL}/api/images/`, {
    headers,
    multipart: { file: { name: 'credit.png', mimeType: 'image/png', buffer: PNG } },
  });
  expect(up.ok(), await up.text()).toBeTruthy();
  const { id, url } = await up.json();
  const patch = await page.request.patch(`${API_BASE_URL}/api/images/${id}/credit/`, {
    headers,
    data: { author: 'Karen Jackson', title: 'Sonnenaufgang', license: 'cc-by-nd', version: '4.0' },
  });
  expect(patch.ok(), await patch.text()).toBeTruthy();
  return url as string;
}

test('presenter shows image credit under the question', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Credits', trackRoom, 'E2E Credits');
  const src = await creditedImage(page);
  const api = apiClient(page.request);
  const q = await api.post('/api/questions/', {
    question_set: room.setId,
    kind: 'single_choice',
    text: { de: `<p>Was sehen Sie?</p><p><img src="${src}" alt=""></p>`, en: '<p>What do you see?</p>' },
    options: [
      { text: { de: 'Ein Bild', en: 'A picture' }, is_correct: true },
      { text: { de: 'Nichts', en: 'Nothing' }, is_correct: false },
    ],
  });
  const runId = await startRun(api, room.setId);
  await control(api, runId, 'open', q.id);
  await page.goto(`/sets/${room.setId}/present?resume=continue`);
  await expect(page.getByText('Bild: „Sonnenaufgang“ von Karen Jackson, CC BY-ND 4.0')).toBeVisible();
  // Presenter output is plain text (beamer): no links.
  await expect(page.locator('[data-testid="image-credits"] a')).toHaveCount(0);
});

test('wide mindmap layout hides question images and therefore the credit', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Credits wide', trackRoom, 'E2E Credits');
  const src = await creditedImage(page);
  const api = apiClient(page.request);
  const q = await api.post('/api/questions/', {
    question_set: room.setId,
    kind: 'mindmap',
    text: { de: `<p>Ideen sammeln</p><p><img src="${src}" alt=""></p>`, en: '' },
    mindmap_root: { de: 'Ideen', en: 'Ideas' },
    mindmap_depth: 2,
    mindmap_max_per_person: 0,
    mindmap_rating_mode: 'points',
    mindmap_rating_budget: 3,
  });
  const runId = await startRun(api, room.setId);
  await control(api, runId, 'open', q.id);
  await page.goto(`/sets/${room.setId}/present?resume=continue`);
  await expect(page.getByText('Ideen sammeln')).toBeVisible();
  await expect(page.getByText(/Karen Jackson/)).toHaveCount(0);
});

test('editor edits image credit', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'Credits editor', trackRoom, 'E2E Credits');
  const token = await csrfToken(page.request);
  const up = await page.request.post(`${API_BASE_URL}/api/images/`, {
    headers: token ? { 'X-CSRFToken': token } : undefined,
    multipart: { file: { name: 'plain.png', mimeType: 'image/png', buffer: PNG } },
  });
  expect(up.ok(), await up.text()).toBeTruthy();
  const { url } = await up.json();
  const api = apiClient(page.request);
  const q = await api.post('/api/questions/', {
    question_set: room.setId,
    kind: 'single_choice',
    text: { de: `<p>Was sehen Sie?</p><p><img src="${url}" alt=""></p>`, en: '' },
    options: [
      { text: { de: 'Ein Bild', en: 'A picture' }, is_correct: true },
      { text: { de: 'Nichts', en: 'Nothing' }, is_correct: false },
    ],
  });

  await page.goto(`/sets/${room.setId}/questions/${q.id}`);
  const section = page.getByTestId('image-credits-editor');
  await expect(section.getByRole('heading', { name: 'Bildnachweise' })).toBeVisible();
  await expect(section.getByText('Kein Bildnachweis')).toBeVisible();

  await section.getByLabel('Urheber:in').fill('Karen Jackson');
  await section.getByRole('combobox', { name: /^Lizenz/ }).selectOption('cc-by');
  await section.getByLabel('Version').fill('4.0');
  await section.getByRole('button', { name: 'Nachweis speichern' }).click();
  await expect(section.getByText('Gespeichert')).toBeVisible();
  await expect(section.getByText('Kein Bildnachweis')).toHaveCount(0);

  // Server-side validation is shown inline.
  await section.getByLabel('Quelle (Link)').fill('ftp://example.org/x');
  await section.getByRole('button', { name: 'Nachweis speichern' }).click();
  await expect(section.getByRole('alert')).toBeVisible();

  await page.reload();
  const again = page.getByTestId('image-credits-editor');
  await expect(again.getByLabel('Urheber:in')).toHaveValue('Karen Jackson');
  await expect(again.getByRole('combobox', { name: /^Lizenz/ })).toHaveValue('cc-by');
  await expect(again.getByLabel('Version')).toHaveValue('4.0');
  await expect(again.getByText('Kein Bildnachweis')).toHaveCount(0);
});
