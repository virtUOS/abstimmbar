/** Phone layout specs (#179): log in once per user and seed the shared room.
 *  Runs as the `mobile-setup` project (a dependency of the phone projects);
 *  `mobile.teardown.ts` deletes the room again. */
import fs from 'node:fs';
import { test as setup, expect, type Page } from '@playwright/test';
import { API_BASE_URL, deleteRooms } from './fixtures';
import {
  AUTH,
  AUTH_DIR,
  SEED_FILE,
  seedManagementRoom,
  sweepStaleE2ERooms,
  writeSeed,
} from './helpers/seed';

async function login(page: Page, username: string, statePath: string) {
  await page.goto(`${API_BASE_URL}/oidc/authenticate/`);
  await page.getByRole('textbox', { name: /Username or email|Benutzername/ }).fill(username);
  await page.getByRole('textbox', { name: /Password|Passwort/ }).fill('demo');
  await page.getByRole('button', { name: /Sign In|Anmelden/ }).click();
  await page.waitForURL('http://localhost:5174/**');
  // whoami also sets the CSRF cookie the API helpers need.
  const whoami = await (await page.request.get(`${API_BASE_URL}/api/whoami/`)).json();
  expect(whoami.username, `login as ${username} failed: ${JSON.stringify(whoami)}`).toBe(username);
  await page.context().storageState({ path: statePath });
}

setup('log in demo + admin-demo and seed the E2E Mobile room', async ({ browser }) => {
  setup.setTimeout(90_000);
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const adminContext = await browser.newContext();
  await login(await adminContext.newPage(), 'admin-demo', AUTH.admin);
  await adminContext.close();

  const context = await browser.newContext();
  const page = await context.newPage();
  await login(page, 'demo', AUTH.demo);

  // Leftovers of runs that died before their teardown: the recorded room id
  // plus any demo-owned room titled "E2E Mobile…" (e.g. a participant room
  // whose test worker was killed).
  if (fs.existsSync(SEED_FILE)) {
    const { roomId } = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8'));
    if (roomId) await deleteRooms(page.request, [roomId]);
    fs.rmSync(SEED_FILE);
  }
  await sweepStaleE2ERooms(page.request);
  // Record the id the moment the room exists, so teardown can always clean up.
  const seed = await seedManagementRoom(page.request, (roomId) => writeSeed({ roomId }));
  writeSeed(seed);
  await context.close();
});
