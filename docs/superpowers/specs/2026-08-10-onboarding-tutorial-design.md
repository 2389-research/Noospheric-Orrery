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

Part 1 ingestion uses a 3-file fixture at `frontend/public/tutorial_samples/` — one article each from
business, politics, and sport, picked from the larger (untracked) `news_small/` folder. Trimmed down
from an earlier 5-file set for a faster, lighter demo; still spans enough categories to exercise the
taxonomy-mismatch behavior below with one fewer domain (no `entertainment` sample) but no loss of the
core point (one anchored domain vs. two that must be invented).

**Known taxonomy mismatch, accepted deliberately**: the current domain taxonomy (`orchestrator/specs/taxonomy.json`) is engineering/org-oriented (`software, business, product, operations, people, research`), not a news-genre taxonomy. Business articles anchor cleanly to the `business` domain; politics/sport/entertainment articles have no matching top-level anchor. The classifier can invent new topics for content that doesn't fit existing anchors (`taxonomy.py`) — the tutorial keeps `news_small/` as-is and treats this as a feature to show off (the taxonomy is open-vocabulary, not a fixed enum), rather than switching to bespoke on-taxonomy sample docs.

## Quest Flow

### Part 1 — "First Light" (ingest → entities/domains → simmer → normalize)
1. **Ingest a document** — upload one or all of the `tutorial_samples/` files, scoped to the sandbox workspace. Completes when `/documents` (sandbox-scoped) shows ≥1 row.
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

- ~~Exact fixture location for `news_small/` inside the repo.~~ Resolved: `frontend/public/tutorial_samples/` (3 files, one per anchored/non-anchored domain).
- Quest 10's fallback graph domain/content.
- ~~Exact name/location of the `design-your-orrery` skill.~~ Resolved: `.claude/skills/design-your-orrery/SKILL.md`.

## Revision 1 — UX feedback from first demo (2026-08-10)

The first implementation rendered every Part/quest as static cards on one long page, all visible at
once. Feedback from trying it:

1. **Not interactive enough, too much on one page.** A wall of cards for every quest across all
   three Parts, all visible from the first paint, reads as a form to scroll through rather than a
   guided experience.
2. **Domains found should be shown**, not just counted. The classify quest showed `Domains found: N`
   — the actual payoff (seeing real domain paths, including invented ones like
   `research/concepts/reference-notes`, next to anchored ones like `business/finance/accounting`)
   was hidden.
3. **The first ingested file should show up immediately**, not on the next 3s poll tick. Ingesting
   one document should feel instant — the response from `POST /ingest` already contains the new
   document's title, domains, and entity_count, and should update UI state synchronously rather than
   waiting for the next polling cycle to reflect it.

### Revised interaction model: one active quest at a time

Replace the all-quests-visible layout with a **single-focus stepper**: only the current active
quest renders as a full card in the main content area; completed quests collapse into the Quest Log
sidebar (already designed) as single lines with their lore blurb, and not-yet-reached quests aren't
rendered in the main area at all (they already exist, greyed out, in the Quest Log — that's the
"what's coming" preview, not a second copy of the interactive card). Advancing to the next quest's
card happens automatically the instant the current quest's completion condition is met — no "Next"
button required for quests that complete via a real action (ingest, simmer, normalize, search), since
the action itself is the advance signal. Quests that require deliberate exploration (e.g. "descend
into a collection") keep a manual "I did this" affordance, per the original design.

This changes the Architecture section's UI shape but not its data model: `TutorialProvider` still
computes quest state from real data, it just also tracks a single `activeQuestIndex` (first
not-done quest in Part order) that the page uses to decide which one card to render.

### Domains: show the list, not the count

The classify quest (and any other place domain count was surfaced) renders the actual list of
domain paths returned by `/domains`, grouped visually into "anchored" (matches an existing taxonomy
path) vs. "invented" (does not) if that distinction is cheap to compute client-side, or as a flat
list of paths if not. The count remains as a small badge, not the primary content.

### Immediate ingest feedback

`ingestFile()`'s response (`{document_id, title, domains, entity_count}`) is applied directly to
local component state the moment each upload call resolves, instead of relying solely on the next
poll tick of `/documents`/`/domains`/`/entities`. The 3s poll remains as the source of truth for
everything the ingest response doesn't cover (job status, normalization state) and to reconcile if
an optimistic update and the polled state ever diverge, but the user sees their first document (and
its domains) appear the moment the request completes, not up to 3 seconds later.

### Sample-file drag-and-drop (2026-08-11)

Added to the ingest quest: the three `tutorial_samples/` files render as small draggable icons
(one per category) with a dedicated drop zone, plus click-to-ingest as a non-drag fallback. Each
icon dims and stops accepting drag/click once its file is ingested. A "load all at once" button
remains for convenience. All paths funnel through one `ingestSample(name)` call so the existing
optimistic-update behavior applies regardless of how the file got in.

## Revision 2 — persistent cross-page panel (2026-08-13)

Feedback: the tutorial should not be confined to its own `/tutorial` stepper page. It should live
as a **panel on the real Upload page**, instructing the user to drag a sample file onto the real
ingestion dropzone there, then prompt them to go check it out on the real Documents page — and this
panel should be **persistent across navigation** (Upload, Pipeline, Documents, etc. within a
workspace), with a minimize/expand toggle, not just present on one dedicated route.

### Where the guidance now lives

- **New quest**: `visit_documents` — completes when the user actually lands on the real Documents
  page for this workspace while it has ≥1 document. Sits between `ingest` and `meet_entities` in the
  quest order, directly implementing "prompt the user to go to Documents" from the request.
- **`useTutorialQuests(noosphereId)`** (`frontend/src/lib/hooks/use-tutorial-quests.ts`): the
  polling/quest-derivation logic factored out of the `/tutorial` page into a shared hook, so both
  the standalone stepper page and the new persistent panel compute quest state the same way instead
  of duplicating it. Covers Part 1's quests (ingest, visit_documents, meet_entities, classify,
  simmer, normalize) — Part 2/3 (search, collection/star navigation, reflect, get-the-skill) remain
  specific to the `/tutorial` page for now; the panel's job is the first-contact flow on the real
  pages, not a full replacement for the guided tour.
- **`TutorialPanel`** (`frontend/src/components/tutorial-panel.tsx`): a fixed-position
  (`bottom-left`) floating panel. Minimize/expand state persists in `localStorage`
  (`tutorial:{id}:panelExpanded`) per workspace, independent of quest progress. Shows the current
  active quest's guidance text, tailored to the current page (e.g. "drag onto the box below" while
  actually on Upload, vs. "head to Upload, then drag one of these in" everywhere else, with a
  "Go to Upload" button). Below that, a compact read-only quest list mirrors the same checkmark
  pattern as the `/tutorial` page's Quest Log sidebar.
- **Mounted in `frontend/src/app/n/[noosphereId]/layout.tsx`**, gated by a
  `tutorial:{id}:enabled` `localStorage` flag — i.e. it renders on every page under `/n/[id]/...`
  (Upload, Pipeline, Documents, Entities, Orrery), not just `/tutorial`. It does not render for the
  Magos demo workspace (`isDemo`).
- **The `/tutorial` entry route now sets that flag and redirects straight to `/n/{id}/upload`**
  instead of `/n/{id}/tutorial` — the guided flow now starts on the real product page with the panel
  narrating it, rather than on a separate stepper page. The standalone `/tutorial` stepper page
  itself is untouched and still reachable directly (e.g. via the nav bar's "✦ Tutorial" link) for
  Part 2/3 and anyone who wants the all-in-one view.

### Making the drag actually work on the real dropzone

The real Upload page's dropzone (`frontend/src/components/file-upload.tsx`) reads
`e.dataTransfer.files` — browsers do not let JS populate that for a drag whose source is another
in-page element (only OS-level file drags carry real `File` objects there). The panel's sample
icons instead set a custom `"text/tutorial-sample"` data type carrying just the filename.
`FileUpload`'s `handleDrop` (new) checks for that type first; if present, it fetches the matching
file from `frontend/public/tutorial_samples/`, builds a `File` from it, and runs it through the
same `ingestFileArray` path a real OS file drop would use — so from the ingestion pipeline's
perspective a tutorial-sample drop and a real file drop are identical.

### Known duplication, accepted for now

`use-tutorial-quests.ts` is only consumed by the panel today; the standalone `/tutorial` page keeps
its own separate, pre-existing state for Part 1 rather than being refactored onto the shared hook in
this pass, to limit the size of this change. This means the two surfaces track ingest/classify/
simmer/normalize progress independently and could in principle drift — acceptable short-term since
both read the same underlying API state, but the `/tutorial` page should be migrated onto
`useTutorialQuests` in a follow-up rather than left permanently forked.

## Revision 3 — Documents → Orrery handoff (2026-08-13)

Feedback: after the "See it in Documents" quest, the panel should prompt the user to **click on the
file they just added** (not just land on the list), without making the Documents list itself go
away — and "ingest more files" should be listed as an **optional** goal, not a blocking step. After
clicking into the document and seeing its extracted entities, the panel should prompt the user to
go see the live view in **Orrery**.

**From this revision on, every code change to the tutorial gets a corresponding entry in this file**
— that's now a standing rule for this feature, not a one-off.

### Quest chain changes (`use-tutorial-quests.ts`)

- **`open_document`** replaces the old `meet_entities` quest. It completes when the user navigates
  to a document *detail* route (`/n/{id}/documents/{docId}` — one segment past the plain list route,
  detected via `isDocumentDetailPath()` in the panel), which is exactly where extracted entities are
  shown (`documents/[id]/page.tsx`, the "Entities · N" section). Landing on the plain Documents list
  does not satisfy this — only opening a specific document does.
- **`view_orrery`** is new: completes on arrival at `/n/{id}/orrery`. Inserted after
  `open_document`, so the flow is now `ingest → visit_documents → open_document → view_orrery →
  classify → simmer → normalize`.
- **`add_more_files`** is new and **optional** (`Quest.optional: true`, a new field). It completes
  once `documentCount > 1`. Optional quests are excluded from `activeQuest` selection entirely — the
  panel never blocks on them or prompts for them as "next" — but they render in their own "Optional"
  section in the panel and quest list, always visible once relevant, so the user can see there's more
  to try without it gating anything.

### Panel behavior (`tutorial-panel.tsx`)

- Visiting the Documents *list* still only marks `visit_documents` (unchanged) — it does **not**
  navigate away or hide the list; the panel is a floating overlay, so "don't make the documents view
  go away" was already true structurally, but this revision makes the wording/quest text explicit
  about not rushing the user past the list ("Click the file you just added" rather than an implicit
  auto-advance).
- New guidance copy for `open_document` ("Click the file you just added to see everything it
  extracted") and `view_orrery` ("Now see it live in the Orrery — every entity you just met, as a
  star"), each with a "Go to X" button when not already on the relevant page, matching the existing
  pattern for `ingest`/`visit_documents`.
- `requiredQuests`/`optionalQuests` split: the quest list at the bottom of the panel now renders in
  two groups (an "Optional" section above the main list) instead of one flat list.

### Known gap carried forward

The standalone `/tutorial` page's own Part 1 state (separate from `useTutorialQuests`, see Revision
2's "Known duplication") was **not** updated with `open_document`/`view_orrery`/`add_more_files` in
this pass — it still has its own `meet_entities`-shaped quest and no Orrery-visit quest. This widens
the gap between the two surfaces beyond what Revision 2 flagged; migrating `/tutorial` onto the
shared hook is now more overdue, not less.

## Bug fix (not a tutorial-design change): `/graph` never invalidated after single-document ingest

While testing the `view_orrery` quest above, the Orrery came up empty for a sandbox workspace that
demonstrably had a document and 35 entities. Root cause, found in `orchestrator/src/routes/ingest.py`:
`/graph` is served from a cached snapshot (`graph_snapshot` table) that a background sweep rebuilds
only for workspaces flagged `dirty` (`orchestrator/src/main.py`, `_rebuild_dirty_snapshots`). Every
other graph-mutating write path calls `mark_graph_dirty(conn)` — `normalize.py`, `corrections.py`,
and the worker's `extract_batch.py` — **except single-document ingest**, which never flagged the
snapshot dirty at all. The very first sweep after server startup builds an empty snapshot (nothing
ingested yet) and clears the dirty bit; every ingest after that point is invisible to `/graph`
forever, for any workspace, not just tutorial sandboxes. This is a pre-existing product bug, not
something introduced by the tutorial — the tutorial's `view_orrery` quest just happened to be the
first thing in this session to actually look at a freshly-ingested workspace's Orrery.

**Fix**: added `mark_graph_dirty(store.conn)` + `store.conn.commit()` at the end of both
`_ingest_document` and `_ingest_image` in `orchestrator/src/routes/ingest.py`, matching the exact
call-then-commit pattern every other caller of `mark_graph_dirty` already uses (the commit matters —
`mark_graph_dirty` only executes an `UPDATE`, and every repository write in this codebase commits
per-call, so a dirty-flag write left uncommitted is silently lost when the connection closes; this
was caught by checking the flag in the workspace's SQLite file directly after ingest, not just by
re-polling `/graph`). Verified end-to-end: ingest → dirty flag reads `1` immediately → after the next
20s background sweep, `/graph` for that workspace reports real node counts instead of zero.

This fix is in `orchestrator/src/routes/ingest.py`, outside the tutorial's own files, but is
recorded here because it was found and fixed in service of making the `view_orrery` quest work at
all — without it, that quest's very first real-world exercise would always show an empty galaxy.

## Revision 4 — add-more-files prompt after Orrery (2026-08-13)

Feedback, after confirming Revision 3 works: once the user has seen the Orrery, the panel should
actively ask if they want to add more files, and going back to Upload should show the same sample
icons from the beginning of the tutorial — not just a message with no way to act on it.

### Quest reordering (`use-tutorial-quests.ts`)

`add_more_files` moved to sit right after `view_orrery` in the quest array (still `optional: true`,
still excluded from `activeQuest` selection — it does not block `classify`/`simmer`/`normalize` from
becoming active). This is purely a display-order change; the array order only affects where it shows
up in the quest list, not when its own prompt appears (see below).

### New: per-file ingested state, not just a count

Previously the hook only exposed `documentCount`; the panel had no way to know *which* of the three
sample files were already ingested, so the ingest quest's icons could only be all-active or (once the
quest was done) not rendered at all. Added `documentTitles: string[]` to the hook (document titles
from `/documents`, already fetched — just wasn't kept before). `SampleIcons` (new, factored out of
the inline JSX) now dims and disables exactly the files whose name appears in `documentTitles`,
regardless of which quest is currently active — the same icon logic that already existed on the
standalone `/tutorial` page's `ingestedSamples` set, now shared by the panel too.

### New: "want to add more files?" prompt, decoupled from the required-quest flow

The panel used to only show the sample icons while `ingest` was the active required quest — once
ingest was satisfied (1 file), the icons disappeared from the panel entirely, even though
`add_more_files` (2+ files) was still incomplete. Added a `showAddMorePrompt` condition
(`viewOrrery.done && !addMoreFiles.done`) that renders a standing card — "Want to add more files?
Same as before — drag one onto the ingestion box on Upload," with the same `SampleIcons` block and a
"Go to Upload" button — independent of whatever the current *required* active quest is (by the time
this shows, that's `classify`/`simmer`/`normalize`, none of which relate to file count). This nudge
naturally disappears once a second file is ingested (`add_more_files.done`), without ever having
blocked or delayed classify/simmer/normalize.

### Why not just re-show the original ingest card

The original ingest card's copy ("Drag one of these onto the ingestion box below to get started")
is written for a first-time user with zero context; reusing it verbatim after Orrery would be
confusing ("get started" when they're clearly already started). The add-more-files prompt has its
own copy while sharing the same `SampleIcons` component and drag/drop mechanics — same interaction,
different framing for where the user actually is in the flow.

## Revision 5 — don't advance quests from free browsing before ingest (2026-08-13)

Feedback: before any document is ingested, the user should be free to browse to any other page
(Orrery, Pipeline, etc. — nothing should block navigation), but doing so must not silently advance
the tutorial past steps the user hasn't actually done.

Before this revision, `markOpenedDocument` and `markVisitedOrrery` (`tutorial-panel.tsx`) fired on
route match alone (`isDocumentDetailPath(pathname)` / `pathname.endsWith("/orrery")`), with no check
on whether there was anything to open/see yet. In practice `open_document`'s route can't really be
hit with zero documents (there's nothing to click into), but `view_orrery` could: a curious user
free-browsing to `/orrery` before ingesting anything would have silently marked that quest done,
later showing "add more files?" or letting `classify`/`simmer`/`normalize` become active despite the
user never having actually completed `ingest`.

**Fix**: both effects now also require `documentCount > 0`, matching the guard `markVisitedDocuments`
already had from Revision 2/3. Verified the page still loads and navigates freely with zero
documents (curl confirms `200`/normal routing) — this only changes whether visiting a page silently
completes a quest, never whether the page itself is reachable.
