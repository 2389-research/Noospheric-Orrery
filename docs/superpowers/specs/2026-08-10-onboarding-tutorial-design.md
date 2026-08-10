# Onboarding Tutorial — Design Spec

Date: 2026-08-10
Branch: `feature/onboarding-tutorial` (off `main`)

## Purpose

An in-app, game-like guided tour of Noospheric Orrery's core loop (main branch), covering:
1. Ingest a file, inspect entities/domains, run a simmer, normalize.
2. Search and navigate the galaxy map's layers.
3. Get inspired to design a custom domain (like the `research_paper` section-spec work on `feature/research-paper-section-spec`) using a new Claude Code skill.

The tour drives the **real app** against a disposable **sandbox workspace**, not a separate mock UI, and not a static walkthrough doc.

## Architecture

- New route `/n/[sandboxId]/tutorial` in the Next.js frontend.
- On entry, call the existing `POST /workspaces` endpoint (`orchestrator/src/routes/workspace_routes.py`) to create a fresh sandbox noosphere. No new backend workspace machinery is needed — this reuses the real multi-workspace mechanism (`ws_id` UUID, fresh SQLite file via `init_db`, tracked in the JSON registry).
- "Always reset on entry": every time `/tutorial` is opened, a **new** sandbox workspace is created (old ones are simply abandoned; cheap since each is a small SQLite file). No explicit wipe-in-place needed.
- All real pages/components used during the tour (documents list, search box, entity panel, galaxy view) are rendered scoped to `sandboxId`, exactly as they would be for a real workspace — no forked/duplicate UI.
- `TutorialProvider` (React context) holds quest state, computed client-side by polling sandbox-scoped orchestrator endpoints (`/documents`, `/jobs`, `/entities`, `/normalize/summary`, `/search`, `/search/concepts`) on a ~3s interval. No new backend state table — quest completion is pure derived state from real data.
- **Live growing thumbnail**: a small (~200x150px), non-interactive `<iframe src="/viz/index.html?...">` (current galaxy view under `frontend/public/viz/`, the modular successor to the old single-file `cosmic-viz.html`) pointed at the sandbox workspace. It mirrors the same `galaxy → collection → star` model the real UI uses, and since it reads live from the same backend, quest completions become visually apparent for free (new stars appear as documents/entities are added) — no changes needed to the viz files themselves.
- A floating **Quest Log** panel overlays the real pages, listing quests grouped by Part, each showing locked/active/done state and a short lore blurb on completion.

## Sample Data

Part 1 ingestion uses the existing (currently untracked) `news_small/` folder — 20 short news articles across business/politics/sport/entertainment, ~92K total. This gets committed into the repo as tutorial fixture data (e.g. `frontend/public/tutorial/news_small/` or an orchestrator-side fixtures dir — exact location decided at implementation time).

**Known taxonomy mismatch, accepted deliberately**: the current domain taxonomy (`orchestrator/specs/taxonomy.json`) is engineering/org-oriented (`software, business, product, operations, people, research`), not a news-genre taxonomy. Business articles anchor cleanly to the `business` domain; politics/sport/entertainment articles have no matching top-level anchor. The classifier can invent new topics for content that doesn't fit existing anchors (`taxonomy.py`) — the tutorial keeps `news_small/` as-is and treats this as a feature to show off (the taxonomy is open-vocabulary, not a fixed enum), rather than switching to bespoke on-taxonomy sample docs.

## Quest Flow

### Part 1 — "First Light" (ingest → entities/domains → simmer → normalize)
1. **Ingest a document** — upload one or all `news_small/` files via the real documents page, scoped to the sandbox workspace. Completes when `/documents` (sandbox-scoped) shows ≥1 row.
2. **Meet your entities** — open a document's reader view / entity list. Completes on first entity-panel view.
3. **Watch it classify** — see domain(s) assigned, including any invented topics. Completes when `/domains` shows ≥2 distinct domains (existing anchor + at least one invented topic).
4. **Run a simmer** — trigger a simmer job from the real UI. Completes when the job's status reaches `completed`.
5. **Normalize** — trigger `/normalize`, resolve one entry from `/normalize/review` if the queue is non-empty. Completes when a `normalization_log` row exists.

Ends with **"First Light"**: the live thumbnail now shows a small galaxy with a handful of lit stars.

### Part 2 — "Full Orbit" (search & layer navigation)
6. **Search** — use the real search box, get entity/chunk results. Completes on a successful `/search?q=` call.
7. **Descend into a collection** — drill galaxy → collection using the real UI. Completes when `viewMode` (`orrery/page.tsx`) transitions `galaxy → collection`.
8. **Zoom to a star** — drill into a single entity. Completes when `viewMode` transitions to `star`.
9. **Ask for inspiration** — use the concept-explorer "inspire" action on an entity panel. Completes on a successful `/search/concepts` call.

Ends with **"Full Orbit."**

### Part 3 — "New Coordinates" (build your own)
10. **Reflect on your Orrery** — shows the user's own sandbox galaxy (built in Parts 1-2), with prompts pointing at what to notice (which entities/domains it found, what felt generic vs. specific, what an invented topic reveals about the taxonomy's open-endedness). Falls back to a prebuilt sample graph if the user skipped ingestion — **fallback content/domain is a placeholder, to be decided later; explicitly not the research-paper domain** (avoid spoiling/duplicating the case study this tutorial is inspired by).
11. **Get the skill** — finale screen introduces a new Claude Code skill (working name `design-your-orrery`, exact name/location TBD at implementation time) that the user can invoke in a real Claude Code session to brainstorm and plan a custom domain spec for their own Orrery. The skill references the `research_paper/` per-section spec pattern (`orchestrator/specs/research_paper/`) as a worked example of what "building your own domain" looks like at the file level. No generated prompt, no idea-starter text box — the screen's job is to name the skill and explain how to invoke it.

No quest-completion tracking needed for quest 11 — it's the finale, not a checkbox.

## Data Flow

`/tutorial` mount → `POST /workspaces` → sandbox `noosphereId` stored in tutorial route state → all page views and API calls scope to that workspace ID via the existing `/n/[noosphereId]` mechanism → `TutorialProvider` polls sandbox-scoped endpoints on ~3s interval to compute quest state → quest completion triggers a lore blurb; the thumbnail iframe updates naturally since it reads the same live `/graph`-equivalent data as the real UI.

## Error Handling

- If sandbox workspace creation fails, show a retry banner rather than entering a broken/missing workspace.
- If a simmer/normalize job fails (real failure states already modeled by the `jobs` table), the quest log surfaces the failure and offers a "retry job" action rather than silently blocking progress.
- If the user navigates away mid-tour and returns, re-entering `/tutorial` creates a new sandbox and restarts Part 1 — called out explicitly in the UI ("Re-entering the tutorial starts a fresh sandbox galaxy") so it isn't a surprise.

## Testing

- Orchestrator: no new backend logic beyond what `POST /workspaces` already provides — no new tests required there unless implementation reveals a gap.
- Frontend: unit-test the quest-state derivation function against fixture API responses (e.g. `documents: []` → quest 1 incomplete; `documents: [...]` → quest 1 complete), rather than full E2E, since the underlying real pages already have their own coverage.
- Manual pass: walk the full tour end-to-end in a browser before calling this done, per the project's UI-testing convention (CLAUDE.md: "For UI or frontend changes, start the dev server and use the feature in a browser before reporting the task as complete").

## Open Items (explicitly deferred, not blocking plan-writing)

- Exact fixture location for `news_small/` inside the repo.
- Quest 10's fallback graph domain/content.
- Exact name/location of the `design-your-orrery` skill.
