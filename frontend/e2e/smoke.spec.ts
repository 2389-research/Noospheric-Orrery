import { test, expect } from "./fixtures";

test.describe("smoke: top-level routes load", () => {
  test("upload page renders + dropzone is keyboard-reachable", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/upload`);
    await expect(page.getByRole("heading", { name: /upload/i })).toBeVisible();
    // Issue #7 / Raj's P0: dropzone must be focusable. Today the component
    // sets role="button" + tabIndex={0} + aria-label="Upload text documents".
    const dropzone = page.getByRole("button", { name: /upload text documents/i });
    await dropzone.focus();
    await expect(dropzone).toBeFocused();
  });

  test("pipeline page renders", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/pipeline`);
    await expect(page.getByRole("heading", { name: /pipeline/i })).toBeVisible();
  });

  test("entities page renders", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/entities`);
    await expect(page).toHaveURL(new RegExp(`/n/${noosphereId}/entities`));
  });

  test("orrery page renders", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/orrery`);
    await expect(page).toHaveURL(new RegExp(`/n/${noosphereId}/orrery`));
  });

  test("noosphere settings page renders and lists at least one noosphere", async ({ page, noosphereId }) => {
    await page.goto(`/settings/noospheres`);
    await page.waitForLoadState("domcontentloaded");
    // The fixture just created a noosphere — it (or any other) should be listed.
    await expect(page.getByText(/e2e-\d+/).first()).toBeVisible({ timeout: 10_000 });
  });
});
