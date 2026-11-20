/** AI rate limit (#343): a throttled AI call (429 with a translated `detail`)
 *  shows that message in the UI — not a generic "Request failed" — and no
 *  native dialog fires. The 429 is stubbed; only an "E2E AI" room is seeded
 *  and deleted. */
import { test, expect, API_BASE_URL } from './fixtures';
import { createRoomWithQuestions } from './helpers/seed';

test.use({ locale: 'de-DE', viewport: { width: 1280, height: 1000 } });

const THROTTLE_DETAIL =
  'Sie haben die KI gerade sehr oft genutzt. Bitte versuchen Sie es in 7 Minuten erneut.';

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
  // Back on the frontend (not Keycloak, not the API origin).
  await page.waitForURL((url) => url.origin !== API_BASE_URL && !url.pathname.startsWith('/realms'));
});

test('throttled rephrase shows the rate-limit message', async ({ page, trackRoom }) => {
  const room = await createRoomWithQuestions(page.request, ['single_choice'], 'KI Limit', trackRoom, 'E2E AI');
  let dialogs = 0;
  page.on('dialog', async (dialog) => {
    dialogs += 1;
    await dialog.dismiss();
  });
  await page.route(/\/api\/questions\/\d+\/ai-rephrase\/$/, (route) =>
    route.fulfill({
      status: 429,
      headers: { 'Retry-After': '420' },
      json: { detail: THROTTLE_DETAIL },
    }),
  );

  await page.goto(`/sets/${room.setId}/questions/${room.questions[0].id}`);
  const panel = page.getByText('Frage umformulieren').locator('xpath=..');
  const button = panel.getByRole('button', { name: 'Vorschläge erzeugen' });
  await button.scrollIntoViewIfNeeded();
  await button.click();

  await expect(page.getByText(THROTTLE_DETAIL)).toBeVisible();
  await expect(page.getByText(/Request failed|429/)).toHaveCount(0);
  expect(dialogs).toBe(0);
});
