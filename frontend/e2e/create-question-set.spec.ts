import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';

/** "+ New room" is a kind menu in expert mode and a plain button in simple
 *  mode; pick the standard room either way. */
async function openNewRoomForm(page: Page) {
  await page.getByRole('button', { name: /New room/ }).click();
  const standard = page.getByRole('menuitem', { name: /^Room/ });
  if (await standard.isVisible()) await standard.click();
}


test('login and create a new question set', async ({ page, trackRoom }) => {
  const runId = Date.now();
  const roomName = `Test Room ${runId}`;
  const setTitle = `Test Fragenset ${runId}`;

  await page.goto('/');
  await page.getByRole('banner').getByRole('link', { name: 'Sign in' }).click();

  await page.getByRole('textbox', { name: 'Username or email' }).fill('demo');
  await page.getByRole('textbox', { name: 'Password' }).fill('demo');
  await page.getByRole('button', { name: 'Sign In' }).click();

  await openNewRoomForm(page);
  await page.getByRole('textbox', { name: 'Name' }).fill(roomName);
  await page.getByRole('button', { name: 'Create' }).click();
  await expect(page.getByRole('heading', { name: roomName })).toBeVisible();

  const roomId = page.url().match(/\/rooms\/(\d+)/)?.[1];
  if (roomId) trackRoom(roomId);

  await page.getByRole('button', { name: '+ New question set' }).click();
  // Set type chooser (#75).
  await page.getByRole('menuitem', { name: /^Live poll/ }).click();
  await page.getByRole('textbox', { name: 'Title' }).fill(setTitle);
  await page.getByRole('button', { name: 'Save' }).click();

  await expect(page.getByRole('heading', { name: setTitle })).toBeVisible();
});
