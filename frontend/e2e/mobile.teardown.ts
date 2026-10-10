/** Deletes the room seeded by mobile.setup.ts (runs after all phone projects). */
import fs from 'node:fs';
import { test as teardown } from '@playwright/test';
import { deleteRooms } from './fixtures';
import { AUTH, SEED_FILE } from './helpers/seed';

teardown('delete the E2E Mobile room', async ({ playwright }) => {
  if (!fs.existsSync(SEED_FILE)) return;
  const request = await playwright.request.newContext({ storageState: AUTH.demo });
  try {
    const { roomId } = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8'));
    if (roomId) await deleteRooms(request, [roomId]);
    fs.rmSync(SEED_FILE);
  } finally {
    await request.dispose();
  }
});
