/** Presenter after the session ended elsewhere (#298): a control action
 *  answered with 403 and a reload both show the "signed out" screen with a
 *  sign-in link, instead of failing silently / hanging at "Connecting …".
 *
 *  "Logged out in another tab" is simulated by dropping the context's
 *  cookies (restored afterwards, so the room cleanup can still delete).
 *  Runs as `demo`; seeds its own "E2E SignedOut …" room. No AI calls. */
import { test, expect, API_BASE_URL } from './fixtures';
import { createRoomWithQuestions } from './helpers/seed';

test.use({ locale: 'en-US', viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL('http://localhost:5174/**');
});

const SIGNED_OUT = /You have been signed out|Sie wurden abgemeldet/;

test('signed out elsewhere: control action and reload show the sign-in screen', async ({
  page,
  trackRoom,
}) => {
  const seed = await createRoomWithQuestions(
    page.request, ['single_choice'], 'X', trackRoom, 'E2E SignedOut',
  );
  await page.goto(`/sets/${seed.setId}/present`);
  await expect(page.locator('[data-tour="present.join"]')).toBeVisible();

  const cookies = await page.context().cookies();
  try {
    await page.context().clearCookies();
    // → first question: a control POST, now rejected.
    await page.keyboard.press('ArrowRight');
    const screen = page.getByRole('alertdialog');
    await expect(screen).toContainText(SIGNED_OUT);
    await expect(screen.getByRole('link', { name: /Sign in|Anmelden/ })).toHaveAttribute(
      'href',
      /\/oidc\/authenticate\/$/,
    );

    await page.reload();
    await expect(page.getByRole('alertdialog')).toContainText(SIGNED_OUT);
  } finally {
    await page.context().addCookies(cookies);
  }
});
