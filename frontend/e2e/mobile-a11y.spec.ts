/** axe accessibility smoke checks at phone width (#179), light and dark.
 *
 *  WCAG 2.0/2.1 A+AA rules except `color-contrast` (owned by the follow-up
 *  contrast PR). Uses the shared "E2E Mobile" seed for the management pages;
 *  the participant page creates its own small room and deletes it. */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { test as base, expect, API_BASE_URL, deleteRooms } from './fixtures';
import {
  AUTH,
  apiClient,
  control,
  createRoomWithQuestions,
  readSeed,
  startRun,
  type Seed,
} from './helpers/seed';

const test = base.extend<{ _tourSeen: void }, { seed: Seed }>({
  seed: [async ({}, use) => use(readSeed()), { scope: 'worker' }],
  // Mark the onboarding tour as seen so it never overlays the page.
  _tourSeen: [
    async ({ page }, use) => {
      await page.route(/\/api\/whoami\/(\?.*)?$/, async (route) => {
        if (route.request().method() !== 'GET') return route.continue();
        const response = await route.fetch();
        const json = await response.json();
        if (json.username) json.onboarding_tour_seen = true;
        await route.fulfill({ response, json });
      });
      await use();
      if (!page.isClosed()) await page.unrouteAll({ behavior: 'ignoreErrors' });
    },
    { auto: true },
  ],
});

async function expectNoAxeViolations(page: Page, where: string) {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .disableRules(['color-contrast'])
    .analyze();
  expect(
    violations.map((v) => ({
      rule: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
    })),
    `axe violations on ${where}`,
  ).toEqual([]);
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`a11y ${colorScheme}`, () => {
    test.use({ colorScheme });

    test.describe('management UI', () => {
      test.use({ storageState: AUTH.demo });

      test('home', async ({ page }) => {
        await page.goto('/');
        await expect(page.locator('[data-tour="rooms.list"]')).toBeVisible();
        await expectNoAxeViolations(page, 'home /');
      });

      test('room page', async ({ page, seed }) => {
        await page.goto(`/rooms/${seed.roomId}`);
        await expect(page.getByText('E2E Fragenset mit langem Titel zum Testen')).toBeVisible();
        await expectNoAxeViolations(page, 'room page');
      });

      test('set page', async ({ page, seed }) => {
        await page.goto(`/sets/${seed.setId}`);
        await expect(page.locator('[data-tour="set.questions"]')).toBeVisible();
        await expectNoAxeViolations(page, 'set page');
      });

      test('question editor (single choice)', async ({ page, seed }) => {
        const q = seed.questions.find((x) => x.kind === 'single_choice')!;
        await page.goto(`/sets/${seed.setId}/questions/${q.id}`);
        await expect(page.locator('[data-tour="question.editor"]')).toBeVisible();
        await expect(page.locator('.ProseMirror').first()).toBeVisible();
        await expectNoAxeViolations(page, 'question editor single_choice');
      });

      test('results page', async ({ page, seed }) => {
        await page.goto(`/sets/${seed.setId}/results`);
        await expect(page.locator('[data-tour="results.view"]')).toBeVisible();
        await expectNoAxeViolations(page, 'results page');
      });
    });

    test.describe('participant', () => {
      test.use({ storageState: { cookies: [], origins: [] } });

      test('open question', async ({ page, playwright }) => {
        const demoApi = await playwright.request.newContext({ storageState: AUTH.demo });
        const created: number[] = [];
        try {
          const room = await createRoomWithQuestions(demoApi, ['open_text'], 'a11y', (id) =>
            created.push(id),
          );
          const api = apiClient(demoApi);
          const runId = await startRun(api, room.setId);
          await control(api, runId, 'open', room.questions[0].id);
          await page.goto(`${API_BASE_URL}/p/${room.code}/`);
          await expect(page.locator('#question')).toBeVisible();
          await expectNoAxeViolations(page, 'participant open question');
        } finally {
          // Close the live page first (a re-joining page breaks the cascade).
          await page.close();
          await deleteRooms(demoApi, created);
          await demoApi.dispose();
        }
      });
    });
  });
}
