/** AI question generation: when the model declines (no questions, with an
 *  "unsuitable_reason"), the set's hint explains why instead of offering to
 *  review "0 questions" (#302), and offers to try again. The job is stubbed;
 *  only an "E2E AI" room is seeded and deleted. */
import { test, expect, API_BASE_URL } from './fixtures';
import { createRoomWithQuestions } from './helpers/seed';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 1000 } });

test.beforeEach(async ({ page }) => {
  await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const json = await response.json();
    if (json.username) Object.assign(json, { onboarding_tour_seen: true, easy_mode: false, ai_enabled: true });
    await route.fulfill({ response, json });
  });
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL('http://localhost:5174/**');
});

test('set hint shows why the material was unsuitable', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, [], 'KI ungeeignet', trackRoom, 'E2E AI');
  const job = {
    id: 1, status: 'done', done_chunks: 1, total_chunks: 1, drafts: [], truncated: false,
    source_chars: 100, notice: 'Aus dem Material ließen sich keine sinnvollen Fragen bilden.',
    unsuitable_reason: 'Es ist nur ein Inhaltsverzeichnis.', error: '', pages: 1, density: 1,
    target_count: 5, reviewed: false,
  };
  await page.route(/\/api\/question-sets\/\d+\/ai-generate\/active\/$/, (route) => route.fulfill({ json: job }));
  await page.route(/\/api\/question-sets\/active-generation\/$/, (route) => route.fulfill({ json: {} }));

  await page.goto(`/sets/${room.setId}`);
  await expect(
    page.getByText('Das Material ist nicht geeignet: Es ist nur ein Inhaltsverzeichnis.'),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Erneut versuchen', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Prüfen', exact: true })).toHaveCount(0);
});
