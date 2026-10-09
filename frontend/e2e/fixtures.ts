import { test as base, expect, type APIRequestContext } from '@playwright/test';

// The dev frontend (5174) and backend (8002) run cross-origin — mirrors
// VITE_API_BASE_URL, see frontend/src/api.ts.
export const API_BASE_URL = process.env.VITE_API_BASE_URL ?? 'http://localhost:8002';

/** Read the CSRF cookie the backend sets (see whoami) from a request context. */
export async function csrfToken(request: APIRequestContext): Promise<string | undefined> {
  const { cookies } = await request.storageState();
  return cookies.find((c) => c.name === 'abstimmbar_csrftoken')?.value;
}

/** Delete rooms (by id) this test run created; throws on any failure. */
export async function deleteRooms(
  request: APIRequestContext,
  roomIds: (number | string)[],
): Promise<void> {
  const token = await csrfToken(request);
  for (const id of roomIds) {
    const response = await request.delete(`${API_BASE_URL}/api/rooms/${id}/`, {
      headers: token ? { 'X-CSRFToken': token } : undefined,
    });
    // 404 = already gone (e.g. a retried teardown) — nothing left to clean up.
    if (!response.ok() && response.status() !== 404) {
      throw new Error(`Cleanup failed: DELETE /api/rooms/${id}/ returned ${response.status()}`);
    }
  }
}

type RoomCleanupFixtures = {
  /** Register a room (by id) for deletion once the test finishes. */
  trackRoom: (roomId: number | string) => void;
};

export const test = base.extend<RoomCleanupFixtures>({
  trackRoom: async ({ page }, use) => {
    const roomIds: (number | string)[] = [];
    await use((roomId) => roomIds.push(roomId));
    await deleteRooms(page.request, roomIds);
  },
});

export { expect };
