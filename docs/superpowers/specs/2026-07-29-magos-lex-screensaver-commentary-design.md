# Magos Lex screensaver commentary — Design

**Status:** Implemented (backend ported to main by PR #77; the frontend overlay shipped earlier)
**Date:** 2026-07-29
**Related:** [ADR-0002](../../adr/0002-graph-as-index-over-code.md) (the graph is a navigational index); `frontend/public/viz/index.html` (attract mode); `frontend/public/mascot/*.png` (Magos artwork)

> **Terminology note (post-rename):** this design was written before the `repos` →
> `collections` rename. Where it says **`repo`** / **`repos.id`** / `node_types: [… "repo"]`,
> the shipped code uses **`collection`** / `collections.id` / `["domain", "collection"]`.
> A repo is one *kind* of collection. Copy request bodies from the code, not from the
> historical examples below.

---

## 1. What this is

When the galaxy idles into **attract mode** (the screensaver) and the camera settles
on a node, the **Magos Lex** mascot appears in the bottom-right corner with a speech
bubble and narrates that node — cycling through three short, pre-generated lines and
swapping pose per line:

1. **description** — what the node is, plainly.
2. **omnissiah** — why its preservation enriches the knowledge of the Omnissiah.
3. **humor** — one dry, structural observation.

Each line carries a **pose** (one of the 7 mascot PNGs); the pose drives which image
shows. Lines are generated **offline, locally, by gemma4** and stored per node.

The overlay is **purely additive and fail-silent**: it renders only when (a) the viewer
has it enabled in settings, and (b) commentary exists for the landed node. A noosphere
with zero commentary behaves exactly as today — no error, attract mode continues.

**Validation already done (spike, 2026-07-29):** the prompt was run on gemma4:26b and
gemma4:e4b against the real `default` workspace (7 repos / 160 domains / 57k entities) —
valid grammar-constrained JSON every call, in-voice and grounded output, and the overlay
was rendered live over the running galaxy at `localhost:3000/n/default/orrery`. Probe:
`scripts/magos_commentary_probe.py` (local-only). Demo artifact captured the e4b-vs-26b
comparison.

## 2. Data model

New table in **both** `orchestrator/src/db.py` and `worker/src/db.py` (WAL, via
`get_connection` as always):

```sql
CREATE TABLE IF NOT EXISTS node_commentary (
    node_type    TEXT,          -- 'entity' | 'domain' | 'repo'
    node_id      TEXT,          -- entities.id | domains.path | repos.id
    comments_json TEXT,         -- [{kind, text, pose}, x3]
    model        TEXT,          -- provenance, e.g. 'gemma4:26b' / 'claude-haiku-4-5'
    source_hash  TEXT,          -- hash of the generation input → idempotency / staleness
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (node_type, node_id)
);
```

Payload (`comments_json`) is always exactly three items, fixed `kind` order:

```json
[
 {"kind":"description","text":"…","pose":"reading"},
 {"kind":"omnissiah",  "text":"…","pose":"galxy"},
 {"kind":"humor",      "text":"…","pose":"pointing"}
]
```

**`pose` is an ASCII enum, not an emoji.** The 7 values map 1:1 to the mascot PNGs and to
a display emoji, resolved on the client:

| pose | png | emoji | tone |
|---|---|---|---|
| `reading` | reading.png | 📖 | studious / describing |
| `galxy` | galxy.png | 🌌 | grand / cosmic significance |
| `pointing` | pointing.png | 👉 | emphatic |
| `thinking` | thinking.png | 🤔 | pondering |
| `happy` | happy.png | 😄 | delight |
| `sad` | sad.png | 😔 | lament |
| `toaster` | toaster.png | 🍞 | absurd / comic |

Using an ASCII enum (not raw emoji) is deliberate: it keeps grammar-constrained decoding
on gemma reliable and avoids emoji-in-grammar tokenization risk. *(Spike confirmed clean
JSON with this shape.)*

## 3. Generation (worker job)

New job type `generate_commentary` in `worker/src/main.py:handle_job`, handler
`worker/src/jobs/generate_commentary.py`. Job `config` (JSON):

```json
{ "node_types": ["domain","collection"], "limit": 50, "only_missing": true, "model": null }
```
(Entities, when scoped in, are always selected top-N by mention — no separate flag.)

**Scope (v1): domains + repos only.** Entities are deferred — their very long tail
isn't worth the backfill, and the screensaver's entity star-dives simply show no
bubble. The job still accepts `"entity"` in `node_types` if we ever want it; the
overlay ignores entity focus (clears rather than fetches).

- Selects in-scope nodes (respecting `only_missing` against `node_commentary`, and for
  entities a **top-N by mention** ranking — see §3.3). The handler runs inside the worker,
  so it reads/writes with raw `get_connection(db_path)` (matches `simmer_domain.py`).
- One **`relay.complete_structured(model, schema, system, messages, max_tokens)` call per
  node** — the backend-agnostic structured path (`relay.py:390`): on **ollama** it passes
  the schema as `format` (grammar-constrained decoding — the model cannot emit invalid
  JSON, and `think:false` is applied internally there); on **bedrock/gateway** it forces a
  `tool_use` call against the schema. **Do not** hand-pass `format`/`think` to plain
  `complete` — on the Anthropic/bedrock path those leak into `messages.create(**kwargs)`
  and raise. (This matters because Spark-on-bedrock is a supported target, §3.1.)
- Validates, snaps any off-set pose to the per-kind default (`description→reading,
  omnissiah→galxy, humor→pointing`), computes `source_hash`, and upserts the row.

### 3.1 Model / backend

The job builds its relay from the worker's settings (`Relay.from_settings`) and takes the
model from `config.model`, defaulting to `settings.extraction_model`. Therefore:
- **Local dev / any box with ollama** → gemma4 (`gemma4:26b` recommended for quality,
  `gemma4:e4b` ~25% faster for the fast path).
- **Spark, if on `bedrock`** → `claude-haiku-4-5` (cheap, strong voice). Gemma-on-Spark
  requires ollama on Spark; this is a config choice, not a code change.

### 3.2 Persona + prompt

System prompt is a compact **Magos Lex** persona block distilled from
`DS-scratch/noospheric_magos_lex_docs/magos_lex_writing_brief.md`: Lexmechanic of the
Adeptus Mechanicus; precision over approximation; **no contractions in prose**; dry, warmth
through attention; short sentences for emphasis; **structural** humour (reports accurately,
never jokes). The user prompt supplies the node context (§3.4) and asks for the three
kinds, each 1–2 sentences, each with a fitting pose.

### 3.3 Per-node-type context builders (mirror production queries)

- **repo** — repo-level `code_intent` summary (`document_repos.level='repo'`) + top ~8
  entities by mention.
- **domain** — `path`, `document_count`, child domain paths, top ~12 entities in the
  domain (`entity_sources ⋈ document_domains`).
- **entity** — `canonical_name`, `type`, top co-occurring entity names (`relationships`,
  with a shared-document fallback), one source-document excerpt.

All entity reads filter `invalid_at IS NULL` so invalidated nodes never narrate.

### 3.4 Scale + capping (measured)

Spike latency: **~7–8s/node (26b), ~5–6s/node (e4b)** single-request on local ollama.
- **domains (160) + repos (7)** ≈ ~20 min — backfill exhaustively.
- **entities (57k)** × ~7s ≈ **5+ days single-threaded** — DO NOT backfill exhaustively.
  Cap to **top-N by mention** (the screensaver only lands on prominent nodes anyway) and
  optionally run a few concurrent ollama requests. The job logs what it skipped (no silent
  truncation).

## 4. Serving (orchestrator)

- `POST /commentary/backfill` — enqueues a `generate_commentary` job. This is the manual
  trigger for both the small test run and the larger backfill (and is what gets called on
  Spark). Body = the job `config` above. Enqueues through the workspace store
  (`auth.store.jobs.create(job_id, "generate_commentary", target, config)`), **not** raw
  SQL — so the job lands in the DB of the noosphere the request targets, and the worker's
  workspace scan (`_find_workspace_dbs`) drains it against that same DB. **This is how
  multi-workspace resolves — no explicit DB selection in the job.**
- `GET /commentary/{node_type}/{node_id:path}` — returns `{comments:[…]}` or **404**. The
  `:path` converter is **required**: a domain's `node_id` is its `domains.path` and
  contains `/` (same pattern as `simmer.py`). The client URL-encodes the id.
- Reads honor the active-graph convention where relevant.

No ingest-time auto-generation in v1 (manual trigger); `source_hash` is stored now so a
"regenerate stale" pass is a later add.

## 5. Frontend

### 5.1 Screensaver settings (device-local)

A **gear control** in the orrery toolbar (`orrery/page.tsx`) opens a small settings
popover. Settings persist in **`localStorage['orrery.screensaver']`** (per-display — a
screensaver preference is inherently per-screen; the kiosk TV and a laptop keep their
own). URL params (`?fps`, `?scale`) still override for kiosk deep-links.

Controls:

| control | drives | default |
|---|---|---|
| **Idle timer** (mins to screensaver) | `ATTRACT_IDLE_MS` (today hardcoded 5 min) | 5 |
| **Magos Lex commentary** on/off | whether the overlay fetches/renders | off |
| **FPS meter** on/off | `set_fps` postMessage to the iframe (today only `?fps`/`f` key) | off |
| **Render scale** | `?scale` forwarded to the iframe | 1.0 |
| **Beat speed** (hop interval) | `ATTRACT_BEAT_MS` | 13 s |

These are shell state; each just drives an existing lever (idle timer, beat, forwarded
param, or a postMessage). **One new inbound viz message is required:** the FPS toggle
needs a `set_fps` handler added to `viz/index.html` (today it only reads `?fps` / the `f`
key). If we want v1 leaner, the FPS toggle can instead set the forwarded `?fps` param and
reload the iframe — no new message. No viz *engine* changes either way.

### 5.2 `attract_focus` message + `<MagosOverlay>`

- **`viz/index.html`:** when attract frames a node (both the galaxy hop and the star
  dive), emit `parent.postMessage({type:'attract_focus', nodeType, id, name})` **alongside**
  the existing `emitSelect`/`enter_star` landing calls (a distinct message type, so it
  doesn't disturb the shell's side-panel logic). The `id` is read **per type** from the
  landed node — `n.id` (entity), `n.repoId` (repo), `n.path` (domain), per `emitSelect` —
  matching the `node_id` contract in §2 (so the repo case must not send a bare `.id`). On
  `attract_stop`/user input, the shell hides the overlay (it already gets those signals).
- **`orrery/page.tsx`:** a new `<MagosOverlay>` DOM component (React, z-indexed over the
  active iframe, bottom-right). On `attract_focus`, **if the Magos setting is on**, it
  `GET`s `/commentary/{type}/{id}`:
  - `200` → render the mascot (`/mascot/{pose}.png`) + bubble, cycling the 3 comments on a
    ~4.5s timer with pose swaps and progress pips.
  - `404` / empty / fetch error / setting off → render nothing. **No throw.**
- Positioned with a bottom offset so it clears the in-iframe FPS meter and the `%` zoom
  readout (both bottom-right). *(Spike surfaced this overlap; offset resolves it.)*

Assets are the app's own `frontend/public/mascot/*.png` — no new assets.

## 6. Spark backfill flow

1. Deploy the schema + job + endpoints + `<MagosOverlay>` to Spark (standard deploy).
2. `POST /commentary/backfill` against Spark's orchestrator with a scoped `config`
   (start small: `{node_types:["domain","collection"], limit:20}`), then widen to entities with
   a `top_by_mention` cap.
3. Spark's worker drains the job against Spark's DB using its configured backend
   (Haiku if bedrock; gemma if ollama present).
4. Because the frontend is fail-silent, overlays "light up" per node as rows land — no
   coordinated release, no downtime, no error if the job hasn't run yet.

## 7. Phasing

- **P0** — schema + `generate_commentary` job + endpoints + context builders.
- **P1** — backfill a small set of **domains + repos** in a local/dev noosphere; tune the
  persona prompt (esp. humor-pose variety). *(Prompt already validated in the spike.)*
- **P2** — settings popover (localStorage) + `<MagosOverlay>` + `attract_focus` wiring;
  verify visually via the `__viz`/screenshot loop.
- **P3** — larger capped backfill across all node types locally, then Spark backfill (§6).
- **Later** — ingest-completion auto-hook; "regenerate stale" via `source_hash`.

## 8. Non-goals (v1)

**Entity-level commentary** (deferred — long tail), ingest-time auto-generation,
regeneration-on-change, personalization, server-side/shared settings, and any change
to attract *timing logic* beyond exposing the existing knobs as settings.

## 9. Risks / open items

- **Entity scale** — mitigated by top-N capping; the full 57k is explicitly out.
- **Humor-pose monotony** — gemma tends to pick `pointing` for humor and `reading` for
  description; e4b more so than 26b. Prompt tuning (P1) or a light post-hoc pose spread.
- **Spark model** — if Spark isn't running ollama, backfill uses Haiku (cost is small;
  quality is good). Decide per deploy.
- **FPS/zoom-readout overlap** — resolved by bottom offset; confirm across breakpoints.
