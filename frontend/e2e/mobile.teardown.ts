/** Deletes the room seeded by mobile.setup.ts (runs after all phone projects). */
import fs from 'node:fs';
import { test as teardown } from '@playwright/test';
import { deleteRooms } from './fixtures';
import { AUTH, SEED_FILE, readSeed } from './helpers/seed';

teardown('delete the E2E Mobile room', async ({ playwright }) => {
  if (!fs.existsSync(SEED_FILE)) return;
  const request = await playwright.request.newContext({ storageState: AUTH.demo });
  await deleteRooms(request, [readSeed().roomId]);
  await request.dispose();
  fs.rmSync(SEED_FILE);
});
