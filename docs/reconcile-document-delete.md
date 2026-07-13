# Merge gate — reconcile document delete (PR #34) with the self-healing loop

**Status:** open. This is a **required reconciliation before this branch merges**, not a
suggestion. See [`graph-corrections.md`](./graph-corrections.md) for the correction model.

## Why this exists

PR #34 (`feat/file-management`) adds **document deletion** — a new capability this branch
has never seen. It **hard-deletes** `entity_sources` (`DELETE FROM entity_sources WHERE
document_id = ?`) and cascades. This branch, by contrast, edits the graph via **soft-delete**
(`entities.invalid_at` / `relationships.invalid_at`). The two use *opposite* deletion
semantics, and the read + rollback layers have to satisfy both. Today they don't.

Nothing is broken in `main` yet, because self-healing isn't shipped — so these hazards are
**latent, not active**. The rule: **do not ship merge/rollback to users until the items
below are done**, or a delete-then-rollback produces an orphaned phantom entity.

## The three problems

1. **`get_trade_routes()` does not filter `invalid_at`.**
   It feeds the main `/graph` galaxy edges via a raw self-join on `entity_sources` +
   `document_domains` — no `entities` join, no `invalid_at` check. So an entity a human
   *invalidates* still renders its domain-to-domain trade routes in the galaxy. (`/graph/umap`
   already filters correctly — copy that shape.) CLAUDE.md claims `invalid_at` is "threaded
   through graph/entities/traversal reads"; this query is the lone violator.

2. **`entity_sources` has no `invalid_at` column.**
   Soft-delete exists only on `entities` and `relationships`. So a document delete has no
   choice but to hard-delete source rows — there is no soft path.

3. **`rollback_merge` depends on `entity_sources` rowid stability.**
   It snapshots `moved_src_rowids` and later `UPDATE ... WHERE rowid IN (...)`, relying on
   its own invariant: *"we only UPDATE entity_id (never DELETE), so rowids never shift."*
   Document hard-delete **does** `DELETE FROM entity_sources`, breaking that invariant.
   Sequence that corrupts data: merge A→B, hard-delete a doc that fed A's sources, then
   `rollback_merge` → re-targets nothing → loser un-invalidated with zero sources = orphan
   phantom. This is a **data** hazard; you cannot fix it after the fact by changing code —
   the rows are already gone.

## The fix — give the system ONE deletion semantic

Do this on this branch, as a merge gate:

- [ ] Add `invalid_at` (+ `invalid_reason`) to the `entity_sources` schema.
- [ ] Change PR #34's `documents` repo `delete()` to **soft-delete** `entity_sources`
      (`UPDATE ... SET invalid_at`) instead of `DELETE`. Restores rollback_merge's
      "never DELETE" invariant.
- [ ] Filter `invalid_at IS NULL` **everywhere** graph data is read, including
      `get_trade_routes()` (join `entities` on both sides of the self-join, mirroring
      `/graph/umap`).
- [ ] Regression test: invalidate an entity → it disappears from `/graph`; merge across a
      soft-deleted document → `rollback_merge` restores cleanly.

One move closes all three: rowids never shift, the galaxy respects invalidation, and
document-delete stops contradicting entity-correction.

## Merge ordering

- Merging PR #34 into `main` **first is safe** — the hazards are latent until this branch
  ships. When this branch rebases onto `main` it inherits `delete()` and rewrites it per the
  checklist above.
- The only hard rule: **never land rollback in `main` without this reconciliation.**
