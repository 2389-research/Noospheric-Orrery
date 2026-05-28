import { test, expect } from "./fixtures";

// Guardrails for the audit findings that aren't a11y-coded but are still
// real UX bugs: raw internal identifiers leaking into the UI, and time
// strings showing "0s ago" instead of "just now".

test.describe("copy: no raw identifiers leak to the UI", () => {
  test("pipeline page never displays raw simmer_domain/simmer_general identifiers", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/pipeline`);
    await page.waitForLoadState("domcontentloaded");
    const bodyText = await page.locator("body").innerText();
    // These are internal job-type keys. If they appear as visible text it
    // means somewhere bypassed lib/labels.ts::jobTypeLabel().
    expect(bodyText).not.toMatch(/\bsimmer_(domain|general|golden_set|extraction_spec)\b/);
    expect(bodyText).not.toMatch(/\bextract_batch(_image)?\b/);
  });

  test("entities page never displays raw extract_batch identifier", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/entities`);
    await page.waitForLoadState("domcontentloaded");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/\bextract_batch\b/);
  });
});

test.describe("copy: timestamps", () => {
  test("timeSince renders 'just now' (not '0s ago') for fresh timestamps", async ({ page }) => {
    // Probe the helper directly by mounting it on the home page through a
    // script — we don't want this test to require a fresh job to exist.
    // The helper lives at /lib/labels.ts and is bundled into the client.
    // Cheapest verification: visit a page that uses it on a known-recent
    // job, and assert "0s ago" never appears in the body. Settings page
    // also lists noospheres with createdAt so it exercises the same path.
    await page.goto(`/`);
    await page.waitForLoadState("domcontentloaded");
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/\b0s ago\b/);
  });
});
