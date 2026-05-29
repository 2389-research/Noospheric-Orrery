import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

// Run axe against every user-facing route. We assert WCAG 2.1 A + AA —
// these are the bars issue #7 (Raj) measured against. Any violation
// fails the build.
const NOOSPHERE_ROUTES = ["upload", "pipeline", "entities", "orrery"] as const;
const SETTINGS_ROUTES = ["/settings/noospheres", "/settings/team"] as const;

function formatViolations(violations: Awaited<ReturnType<AxeBuilder["analyze"]>>["violations"]) {
  return violations
    .map(
      (v) =>
        `  - [${v.impact}] ${v.id}: ${v.help}\n` +
        `    ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target}`
    )
    .join("\n");
}

async function scan(page: import("@playwright/test").Page, tags: string[]) {
  await page.waitForLoadState("domcontentloaded");
  return new AxeBuilder({ page }).withTags(tags).analyze();
}

for (const route of NOOSPHERE_ROUTES) {
  for (const [label, tags] of [["A", ["wcag2a"]], ["AA", ["wcag2aa"]]] as const) {
    test(`a11y Level ${label}: /n/{id}/${route}`, async ({ page, noosphereId }) => {
      await page.goto(`/n/${noosphereId}/${route}`);
      const results = await scan(page, tags as string[]);
      if (results.violations.length > 0) {
        console.log(`\n[${route}] ${results.violations.length} Level ${label} violation(s):\n${formatViolations(results.violations)}`);
      }
      expect(results.violations, `${results.violations.length} WCAG-${label} violations on /${route}`).toEqual([]);
    });
  }
}

for (const route of SETTINGS_ROUTES) {
  for (const [label, tags] of [["A", ["wcag2a"]], ["AA", ["wcag2aa"]]] as const) {
    test(`a11y Level ${label}: ${route}`, async ({ page }) => {
      await page.goto(route);
      const results = await scan(page, tags as string[]);
      if (results.violations.length > 0) {
        console.log(`\n[${route}] ${results.violations.length} Level ${label} violation(s):\n${formatViolations(results.violations)}`);
      }
      expect(results.violations, `${results.violations.length} WCAG-${label} violations on ${route}`).toEqual([]);
    });
  }
}
