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

// Real end-to-end ingest: drive the actual <input type="file"> the
// dropzone delegates to, and confirm the UI reflects a successful
// extraction. Requires the orchestrator's LLM backend to be configured
// (Bedrock / gateway / Ollama), so it's skipped in CI / no-LLM envs.
test.describe("flow: upload via UI", () => {
  test.skip(
    !!process.env.SKIP_LLM_TESTS,
    "SKIP_LLM_TESTS set — flow tests require a live LLM backend"
  );

  test("uploading a text file shows extraction result", async ({ page, noosphereId }) => {
    await page.goto(`/n/${noosphereId}/upload`);
    await expect(page.getByRole("heading", { name: /upload/i })).toBeVisible();

    // The dropzone delegates to a hidden <input id="text-file-input">.
    // setInputFiles works on display:none inputs.
    await page.locator("#text-file-input").setInputFiles({
      name: "smoke-upload.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# Smoke test note\n\nThis is an end-to-end upload from a Playwright test. " +
          "Acme Corp and OpenAI are mentioned so the extractor has something to find.\n"
      ),
    });

    // Pipeline may take a few seconds (chunk → classify → extract).
    // Wait for the upload-status component's "1 file uploaded" line.
    await expect(page.getByText(/1 file uploaded/i)).toBeVisible({ timeout: 60_000 });
    // And confirm the per-file row appears with the filename.
    await expect(page.getByText("smoke-upload.md")).toBeVisible();
  });
});
