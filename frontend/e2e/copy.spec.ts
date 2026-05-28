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

test.describe("copy: input placeholders", () => {
  // Issue #7 (Margaret): placeholders should be sentence-cased and not
  // end with trailing dots. Lock in the convention on the inputs we have.
  const ROUTES_WITH_INPUTS = [
    { route: "entities", expected: /^Search entities$/ },
    { route: "orrery", expected: /^Search the knowledge graph$/ },
  ];

  for (const { route, expected } of ROUTES_WITH_INPUTS) {
    test(`${route} search input has sentence-cased placeholder`, async ({ page, noosphereId }) => {
      await page.goto(`/n/${noosphereId}/${route}`);
      await page.waitForLoadState("domcontentloaded");
      // Target the textbox by its accessible name rather than locator order,
      // so this can't latch onto a different input if the layout shifts.
      const searchInput = page.getByRole("textbox", { name: /search/i });
      const placeholder = await searchInput.getAttribute("placeholder");
      expect(placeholder).toMatch(expected);
      // Belt-and-suspenders: no trailing dots, no lowercase first letter.
      expect(placeholder).not.toMatch(/\.{1,3}$/);
      expect(placeholder?.[0]).toMatch(/[A-Z]/);
    });
  }
});

test.describe("copy: timestamps", () => {
  test("timeSince renders 'just now' (not '0s ago') for fresh timestamps", async ({ page, noosphereId }) => {
    // /settings/noospheres renders one row per noosphere with a
    // relative timestamp on `createdAt`. The fixture just created one
    // < 1 second ago — perfect for catching a "0s ago" regression.
    await page.goto(`/settings/noospheres`);
    await page.waitForLoadState("domcontentloaded");
    await expect(page.getByText(new RegExp(`e2e-\\d+`)).first()).toBeVisible({ timeout: 10_000 });
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/\b0s ago\b/);
  });
});
