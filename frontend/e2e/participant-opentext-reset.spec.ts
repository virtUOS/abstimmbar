/** Free text (#277): the participant page shares one textarea between all
 *  open_text questions. Moving on to the next free-text question must clear
 *  it — before, the previous answer stayed in the field and was submitted
 *  mixed into the next one.
 *
 *  Runs as `demo` (API seeding only); the participant is anonymous. Seeds
 *  its own "E2E Freetext …" room and deletes it. No AI calls. */
import { test, expect, API_BASE_URL } from './fixtures';
import { apiClient, control, createRoomWithQuestions, startRun } from './helpers/seed';

test.use({ locale: 'en-US', viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL(`${process.env.E2E_BASE_URL ?? 'http://localhost:5174'}/**`);
});

test('the next free-text question starts with an empty field', async ({ page, browser, trackRoom }) => {
  const seed = await createRoomWithQuestions(
    page.request, ['open_text', 'open_text'], 'Reset', trackRoom, 'E2E Freetext',
  );
  const api = apiClient(page.request);
  const runId = await startRun(api, seed.setId);
  const [first, second] = seed.questions;

  const ctx = await browser.newContext({ locale: 'en-US' });
  const p = await ctx.newPage();
  try {
    await p.goto(`${API_BASE_URL}/p/${seed.code}/`);
    await control(api, runId, 'open', first.id);
    const field = p.locator('#opentext-input');
    await expect(field).toBeVisible();
    await field.fill('Antwort auf Frage A');
    await p.locator('#opentext button[type="submit"], #opentext button').first().click();
    await expect(p.locator('#done')).toBeVisible();

    await control(api, runId, 'open', second.id);
    await expect(field).toBeVisible();
    await expect(field).toHaveValue('');

    // Typing in the second question survives background re-renders
    // (another participant's vote broadcast) — only a question change clears.
    await field.fill('Zwischenstand');
    await control(api, runId, 'open', second.id);
    await expect(field).toHaveValue('Zwischenstand');
  } finally {
    await ctx.close();
  }
});
