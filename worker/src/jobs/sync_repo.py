# ABOUTME: Repo adapter for incremental sync — summarize a repo into leaf/group/root docs.
# ABOUTME: Reuses the spine: upsert_document per artifact, apply_deletions for gone files.
"""The repo adapter (spec 2026-08-14 incremental-source-sync §15 / Spec 2).

A repo source enumerates the working tree via codesum into three doc roles — `file`
(leaf, per-file intent, emits co-occurrence), `module` (group), `repo` (root rollup);
only leaves emit. Each artifact is upserted through the shared primitive with repo-shaped
params, so identity, change detection, projection, and soft-delete all come from the spine.

This is the FULL-TREE version: it re-summarizes the whole repo each scan. Per-file
content_hash still makes re-extraction of unchanged summaries a no-op (skip), but codesum
itself runs over everything. The git-diff short-circuit (only re-featurize changed files)
and threshold-gated module/root regeneration are layered on top of this in follow-ups.
"""
import asyncio
import json
import os
import subprocess
import uuid

from orrery_codesum import summarize_repo, make_summarize_fn

from ..classifier import classify_document
from .upsert_document import upsert_document
from .scan_source import apply_deletions

_UNCLASSIFIED = "unclassified/needs-review"
_ROLE = {"file": "leaf", "module": "group", "repo": "root"}


def _git_head_sha(root_path: str) -> str | None:
    """Current HEAD sha, or None if `root_path` is not a resolvable git checkout.
    Used to short-circuit a scan when the working tree hasn't moved since last sync."""
    try:
        out = subprocess.run(["git", "-C", root_path, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001 — git missing / not a repo -> no short-circuit
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _resolve_collection(conn, root_path: str, source_config: dict) -> tuple[str, str]:
    """Return (collection_id, collection_path). Reuse the stored collection for this
    source if present, else find-or-create one keyed on a stable path."""
    coll_path = source_config.get("collection") or os.path.basename(os.path.normpath(root_path))
    row = conn.execute("SELECT id FROM collections WHERE path = ?", (coll_path,)).fetchone()
    if row:
        return row["id"], coll_path
    collection_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path, kind) VALUES (?, ?, ?, ?, 'git_repo')",
        (collection_id, coll_path, coll_path, root_path))
    conn.commit()
    return collection_id, coll_path


async def _repo_domain(conn, relay, settings, ws, source_config, source_id,
                       coll_path, artifacts) -> str:
    """Classify the repo ONCE on its grounded root summary, then reuse. Stored in
    config_json under a reserved key so later scans don't reclassify (and churn domains)."""
    if source_config.get("_domain"):
        return source_config["_domain"]
    root_summary = next((a["intent"] for a in artifacts if a["level"] == "repo"), "")
    taxonomy = [r[0] for r in conn.execute("SELECT path FROM domains").fetchall()]
    try:
        classification = await classify_document(
            relay=relay, title=coll_path,
            excerpt=f"Repository: {coll_path}\n\n{root_summary}",
            existing_taxonomy=taxonomy, model=settings.classification_model)
        domain_path = classification.get("primary_domain") or _UNCLASSIFIED
    except Exception as e:  # noqa: BLE001 — keep the artifacts even if classification fails
        print(f"[sync_repo] classify failed ({type(e).__name__}: {e}); filing under {_UNCLASSIFIED}", flush=True)
        domain_path = _UNCLASSIFIED
    source_config["_domain"] = domain_path
    conn.execute("UPDATE watched_sources SET config_json = ? WHERE id = ?",
                 (json.dumps(source_config), source_id))
    conn.commit()
    return domain_path


async def sync_repo(conn, relay, settings, ws, source_config, source_id) -> dict:
    root_path = ws["uri"]
    collection_id, coll_path = _resolve_collection(conn, root_path, source_config)

    # Source-level short-circuit (spec §4/§15): if HEAD hasn't moved since the last
    # successful sync, nothing changed — skip codesum entirely (zero model calls). The
    # commit_sha doubles as the git provenance ref, so storing it here keeps that fresh.
    head_sha = _git_head_sha(root_path)
    stored = conn.execute("SELECT commit_sha FROM collections WHERE id = ?", (collection_id,)).fetchone()
    stored_sha = stored["commit_sha"] if stored else None
    if head_sha and stored_sha and head_sha == stored_sha:
        return {"actions": {"created": 0, "updated": 0, "skipped": 0, "conflict": 0},
                "deleted": 0, "unchanged": True}

    # codesum traversal is synchronous and issues one blocking model call per file/
    # module/repo — run it off the event loop so the poll loop keeps ticking.
    summarize_fn = make_summarize_fn(relay, settings.extraction_model)
    artifacts = await asyncio.to_thread(summarize_repo, root_path, summarize_fn, coll_path)

    domain_path = await _repo_domain(conn, relay, settings, ws, source_config, source_id,
                                     coll_path, artifacts)

    seen_paths: set[str] = set()
    actions = {"created": 0, "updated": 0, "skipped": 0, "conflict": 0}
    for a in artifacts:
        role = _ROLE.get(a["level"], "leaf")
        source_path = os.path.join(root_path, a["path"])
        seen_paths.add(source_path)
        res = await upsert_document(
            conn, relay, settings, source_path=source_path, title=a["path"],
            content=a["intent"], source_id=source_id, collection_id=collection_id,
            role=role, parent_path=a.get("parent_path"), content_type="code_intent",
            domain_path=domain_path, classify=False, pre_chunked=True,
            emits_cooccurrence=(role == "leaf"))
        actions[res["action"]] = actions.get(res["action"], 0) + 1

    deleted = apply_deletions(conn, source_id, seen_paths)

    # Record the synced commit so the next scan can short-circuit (and so the graph's
    # git ref points at the code these summaries actually describe).
    if head_sha:
        conn.execute("UPDATE collections SET commit_sha = ? WHERE id = ?", (head_sha, collection_id))

    return {"actions": actions, "deleted": deleted}
