/** Section headers ("Zwischenfolie") in the presenter (#278): a fixed place
 *  in the sequence — every step forward into a section shows its header,
 *  every step back from a section's first question shows it again, a step
 *  back from the header goes to the previous question itself, and the jump
 *  menu ("3/4") lands on the chosen question, not on a header.
 *
 *  Runs as `demo` (logs in per test); seeds its own "E2E Sections …" room
 *  and deletes it. No AI calls. */
import type { Page } from '@playwright/test';
import { test, expect, API_BASE_URL, csrfToken } from './fixtures';
import { apiClient, createRoomWithQuestions } from './helpers/seed';

test.use({ locale: 'en-US', viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL(`${process.env.E2E_BASE_URL ?? 'http://localhost:5174'}/**`);
});

const position = (page: Page) => page.locator('footer [data-help="position"]');
const header = (page: Page) => page.getByTestId('section-interstitial');

async function expectHeader(page: Page, title: string) {
  await expect(header(page).getByRole('heading', { name: title })).toBeVisible();
}
async function expectQuestion(page: Page, pos: string) {
  await expect(header(page)).toHaveCount(0);
  await expect(position(page)).toHaveText(pos);
}

test('section headers keep their place when paging; jumps skip them', async ({ page, trackRoom }) => {
  const seed = await createRoomWithQuestions(
    page.request,
    ['single_choice', 'single_choice', 'single_choice', 'single_choice'],
    'Nav',
    trackRoom,
    'E2E Sections',
  );
  const api = apiClient(page.request);
  // Previews only: an open vote would trigger the "still running" prompt.
  const token = await csrfToken(page.request);
  const patch = await page.request.patch(`${API_BASE_URL}/api/question-sets/${seed.setId}/`, {
    data: { open_on_show: false },
    headers: token ? { 'X-CSRFToken': token } : undefined,
  });
  expect(patch.ok()).toBeTruthy();
  const a = await api.post('/api/sections/', { question_set: seed.setId, title: { de: 'Teil A', en: 'Part A' } });
  const b = await api.post('/api/sections/', { question_set: seed.setId, title: { de: 'Teil B', en: 'Part B' } });
  const [q1, q2, q3, q4] = seed.questions.map((q) => ({ type: 'question', id: q.id }));
  await api.post(`/api/question-sets/${seed.setId}/reorder-outline/`, {
    items: [{ type: 'section', id: a.id }, q1, q2, { type: 'section', id: b.id }, q3, q4],
  });

  await page.goto(`/sets/${seed.setId}/present`);
  await expect(page.locator('[data-tour="present.join"]')).toBeVisible();

  // Forward: A → 1 → 2 → B → 3.
  await page.keyboard.press('ArrowRight');
  await expectHeader(page, 'Part A');
  await page.keyboard.press('ArrowRight');
  await expectQuestion(page, '1/4');
  await page.keyboard.press('ArrowRight');
  await expectQuestion(page, '2/4');
  await page.keyboard.press('ArrowRight');
  await expectHeader(page, 'Part B');
  await page.keyboard.press('ArrowRight');
  await expectQuestion(page, '3/4');

  // Back: 3 → B → 2 (the question itself, not header A).
  await page.keyboard.press('ArrowLeft');
  await expectHeader(page, 'Part B');
  await page.keyboard.press('ArrowLeft');
  await expectQuestion(page, '2/4');

  // Forward again: header B shows again (it used to be skipped once seen).
  await page.keyboard.press('ArrowRight');
  await expectHeader(page, 'Part B');
  await page.keyboard.press('ArrowRight');
  await expectQuestion(page, '3/4');

  // Jump menu: lands on the chosen question — also on a section's first one.
  await position(page).click();
  const jump = page.getByRole('menu', { name: /Jump to a question|Zu einer Frage springen/ });
  await jump.getByRole('menuitem').nth(0).click();
  await expectQuestion(page, '1/4');
  await position(page).click();
  await jump.getByRole('menuitem').nth(3).click();
  await expectQuestion(page, '4/4');
});

test('leaving a header never flashes the previous question', async ({ page, trackRoom }) => {
  const seed = await createRoomWithQuestions(
    page.request, ['single_choice', 'single_choice'], 'Flash', trackRoom, 'E2E Sections',
  );
  const api = apiClient(page.request);
  const token = await csrfToken(page.request);
  await page.request.patch(`${API_BASE_URL}/api/question-sets/${seed.setId}/`, {
    data: { open_on_show: false },
    headers: token ? { 'X-CSRFToken': token } : undefined,
  });
  const b = await api.post('/api/sections/', { question_set: seed.setId, title: { de: 'Teil B', en: 'Part B' } });
  const [q1, q2] = seed.questions.map((q) => ({ type: 'question', id: q.id }));
  await api.post(`/api/question-sets/${seed.setId}/reorder-outline/`, {
    items: [q1, { type: 'section', id: b.id }, q2],
  });

  await page.goto(`/sets/${seed.setId}/present`);
  await expect(page.locator('[data-tour="present.join"]')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expectQuestion(page, '1/2');
  await page.keyboard.press('ArrowRight');
  await expectHeader(page, 'Part B');

  // Delay the control call: until the server reports question 2, the header
  // must stay up (before, question 1 reappeared in between).
  await page.route('**/api/runs/*/control/', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue();
  });
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(600);
  await expect(header(page)).toBeVisible();
  await expectQuestion(page, '2/2');
});
