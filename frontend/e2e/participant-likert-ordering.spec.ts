/** Participant page, 1.0.x fixes:
 *  - #282: an unlabeled Likert step confirms as "4 of 5" instead of an empty
 *    "Your answer:" (done view, server resume, "My answers").
 *  - #281: the own "▲ you" marker sits at the step's scale position.
 *  - #283: an ordering question in a quiz block (self-paced) gets right/wrong
 *    feedback and counts in the personal evaluation.
 *
 *  Runs as `demo` (API seeding only); the participant is anonymous. Seeds its
 *  own "E2E Participant …" rooms and deletes them. No AI calls. */
import { test, expect, API_BASE_URL } from './fixtures';
import { apiClient, control, createRoomWithQuestions, startRun } from './helpers/seed';

test.use({ locale: 'en-US', viewport: { width: 1280, height: 800 } });

const T = (de: string, en = '') => ({ de, en });

test.beforeEach(async ({ page }) => {
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill('demo');
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL(`${process.env.E2E_BASE_URL ?? 'http://localhost:5174'}/**`);
});

test('an unlabeled Likert step confirms as "4 of 5"; own marker at its scale position', async ({
  page,
  browser,
  trackRoom,
}) => {
  const seed = await createRoomWithQuestions(page.request, [], 'Likert', trackRoom, 'E2E Participant');
  const api = apiClient(page.request);
  // Endpoint-only scale: the three middle steps carry no label.
  const q = await api.post('/api/questions/', {
    question_set: seed.setId,
    kind: 'likert',
    text: T('<p>Wie zufrieden sind Sie?</p>', '<p>How satisfied are you?</p>'),
    options: ['Gar nicht', '', '', '', 'Sehr'].map((x) => ({ text: T(x, x) })),
  });
  const runId = await startRun(api, seed.setId);

  const ctx = await browser.newContext({ locale: 'en-US' });
  const p = await ctx.newPage();
  try {
    await p.goto(`${API_BASE_URL}/p/${seed.code}/`);
    await control(api, runId, 'open', q.id);
    await p.locator('#likert .likert-seg').nth(3).click();
    await p.locator('#likert').getByRole('button', { name: 'Submit answer' }).click();
    await expect(p.locator('#done')).toBeVisible();
    await expect(p.locator('#done-answer')).toContainText('Your answer: 4 of 5');

    // A second tab (same token, empty session history) trying another step
    // is refused (409) and shows the answer the server has (#282).
    const p2 = await ctx.newPage();
    await p2.goto(`${API_BASE_URL}/p/${seed.code}/`);
    await p2.locator('#likert .likert-seg').nth(1).click();
    await p2.locator('#likert').getByRole('button', { name: 'Submit answer' }).click();
    await expect(p2.locator('#done-answer')).toContainText('Your answer: 4 of 5');

    // #281: the "you" marker sits at step 4's scale position (3.5 / 5 =
    // 70 %, like the mean tick) — not mid-segment of the only voted step.
    await control(api, runId, 'results', q.id);
    const marker = p.locator('#results-list span', { hasText: '▲' });
    await expect(marker).toBeVisible();
    expect(await marker.evaluate((el) => (el as HTMLElement).style.left)).toBe('70%');

    // "My answers" review shows the same answer text.
    await p.locator('#menu-btn').click();
    await p.locator('#review-open').click();
    await expect(p.locator('#review-list')).toContainText('Your answer: 4 of 5');
  } finally {
    await ctx.close();
  }
});

test('a quiz-block ordering question is graded and counted', async ({ page, browser, trackRoom }) => {
  const seed = await createRoomWithQuestions(page.request, [], 'Ordering', trackRoom, 'E2E Participant');
  const api = apiClient(page.request);
  const set = await api.post('/api/question-sets/', {
    room: seed.roomId,
    type: 'self_paced',
    title: T('E2E Quiz-Block', 'E2E quiz block'),
  });
  const solution = ['Eins', 'Zwei', 'Drei'];
  await api.post('/api/questions/', {
    question_set: set.id,
    kind: 'ordering',
    text: T('<p>Sortieren Sie</p>', '<p>Sort these</p>'),
    options: solution.map((x) => ({ text: T(x, x) })),
  });
  await api.post(`/api/question-sets/${set.id}/start-run/`, { mode: 'self_paced', existing: 'delete' });

  const ctx = await browser.newContext({ locale: 'en-US' });
  const p = await ctx.newPage();
  try {
    await p.goto(`${API_BASE_URL}/p/${seed.code}/`);
    const rows = p.locator('#quiz .ordering-row');
    await expect(rows).toHaveCount(3);
    // Bring the (shuffled) rows into the authored order with the ▲ buttons.
    for (let target = 0; target < solution.length; target++) {
      for (;;) {
        const texts = await rows.allInnerTexts();
        const at = texts.findIndex((t) => t.includes(solution[target]));
        if (at <= target) break;
        await rows.nth(at).locator('.ord-up').click();
      }
    }
    await p.locator('#quiz').getByRole('button', { name: 'Submit', exact: true }).click();
    await expect(p.locator('#quiz-feedback')).toHaveText('✓ Correct!');
    await expect(p.locator('#quiz')).toContainText('Correct order');
    await p.locator('#quiz-next').click();
    await expect(p.locator('#quiz-summary')).toHaveText('Done! 1 of 1 auto-graded questions correct.');
  } finally {
    await ctx.close();
  }
});
