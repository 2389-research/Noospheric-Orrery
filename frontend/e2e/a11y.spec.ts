import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";

// Run axe against each top-level route. We assert WCAG 2.0 Level A as the
// floor — these are the must-fix violations from issue #7 (Raj). AA tier
// is run separately below so we can lock in the Level A baseline even
// while AA work is in flight.
const ROUTES = ["upload", "pipeline", "entities", "orrery"] as const;

function formatViolations(violations: Awaited<ReturnType<AxeBuilder["analyze"]>>["violations"]) {
  return violations
    .map(
      (v) =>
        `  - [${v.impact}] ${v.id}: ${v.help}\n` +
        `    ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target}`
    )
    .join("\n");
}

for (const route of ROUTES) {
  test(`a11y Level A: /n/{id}/${route}`, async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/${route}`);
    // Avoid networkidle — the orrery page keeps a websocket open.
    await page.waitForLoadState("domcontentloaded");

    const results = await new AxeBuilder({ page }).withTags(["wcag2a"]).analyze();

    if (results.violations.length > 0) {
      console.log(`\n[${route}] ${results.violations.length} Level A violation(s):\n${formatViolations(results.violations)}`);
    }
    expect(results.violations, `${results.violations.length} WCAG-A violations on /${route}`).toEqual([]);
  });

  // AA tier reports informationally for now. Flip the .fixme to a regular
  // test once issue #7 P1/P2 backlog is cleared.
  test.fixme(`a11y Level AA: /n/{id}/${route} (informational)`, async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/${route}`);
    await page.waitForLoadState("domcontentloaded");
    const results = await new AxeBuilder({ page }).withTags(["wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);
  });
}
