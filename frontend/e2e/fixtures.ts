import { test as base, expect } from '@playwright/test';

// The dev frontend (5174) and backend (8002) run cross-origin — mirrors
// VITE_API_BASE_URL, see frontend/src/api.ts.
const API_BASE_URL = process.env.VITE_API_BASE_URL ?? 'http://localhost:8002';

type RoomCleanupFixtures = {
  /** Register a room (by id) for deletion once the test finishes. */
  trackRoom: (roomId: number | string) => void;
};

export const test = base.extend<RoomCleanupFixtures>({
  trackRoom: async ({ page }, use) => {
    const roomIds: (number | string)[] = [];
    await use((roomId) => roomIds.push(roomId));

    const cookies = await page.context().cookies();
    const csrfToken = cookies.find((c) => c.name === 'csrftoken')?.value;
    for (const id of roomIds) {
      const response = await page.request.delete(`${API_BASE_URL}/api/rooms/${id}/`, {
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : undefined,
      });
      if (!response.ok()) {
        throw new Error(
          `Cleanup failed: DELETE /api/rooms/${id}/ returned ${response.status()}`
        );
      }
    }
  },
});

export { expect };
