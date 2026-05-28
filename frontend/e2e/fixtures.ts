import { test as base } from "@playwright/test";

// Create a throwaway noosphere per test run so tests don't depend on
// whatever state the dev's local stack happens to be in. The fixture
// returns the noosphere id; cleanup is best-effort.
export const test = base.extend<{ noosphereId: string }>({
  noosphereId: async ({ request }, use) => {
    const apiBase = process.env.API_URL ?? "http://localhost:8100";
    const create = await request.post(`${apiBase}/workspaces`, {
      data: { name: `e2e-${Date.now()}`, description: "playwright fixture" },
    });
    const { workspaceId } = await create.json();
    await use(workspaceId);
    // Soft-delete on teardown
    await request.delete(`${apiBase}/workspaces/${workspaceId}`).catch(() => {});
  },
});

export { expect } from "@playwright/test";
