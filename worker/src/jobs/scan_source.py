# ABOUTME: scan_source — re-scan one watched source, applying the §6 decision table.
# ABOUTME: create/update/skip via upsert_document; soft-delete paths the source dropped.
"""The adapter dispatch (spec 2026-08-14 incremental-source-sync 10).

Resolves a featurizer by the source `type`, enumerates its current
`(source_path, title, content, emits_cooccurrence)` tuples, upserts each, then
soft-deletes any document this source used to own whose path is no longer present.
"""
import json

from orrery_relay import Relay
from ..db import get_connection, mark_graph_dirty, recompute_cooccurrence
from ..config import get_settings
from .upsert_document import upsert_document

# Test/extension hook: a mapping of source-type -> featurizer callable. A featurizer is
# `(uri, config) -> iterable[(source_path, title, content, emits_cooccurrence)]`. Built-in
# types are resolved lazily below so this module imports without the featurizer packages.
_FEATURIZERS: dict = {}


def _resolve_featurizer(source_type: str):
    if source_type in _FEATURIZERS:
        return _FEATURIZERS[source_type]
    if source_type == "vault":
        from ..featurizers.vault import enumerate_vault
        return enumerate_vault
    raise ValueError(f"no featurizer registered for source type {source_type!r}")


def _soft_delete_document(conn, doc_id: str) -> None:
    """Soft-delete a document and retract its derived rows (spec §8). The doc row
    survives (a re-appearing file re-attaches to the same identity); its chunks and
    entity_sources are hard-removed; entities left with no sources are soft-deleted;
    co-occurrence is recomputed for the affected neighbourhood."""
    affected = [r[0] for r in conn.execute(
        "SELECT DISTINCT entity_id FROM entity_sources WHERE document_id = ?", (doc_id,)).fetchall()]
    conn.execute("DELETE FROM entity_sources WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
    conn.execute("UPDATE documents SET invalid_at = CURRENT_TIMESTAMP WHERE id = ?", (doc_id,))
    for eid in affected:
        remaining = conn.execute(
            "SELECT COUNT(*) c FROM entity_sources WHERE entity_id = ?", (eid,)).fetchone()["c"]
        if remaining == 0:
            conn.execute(
                "UPDATE entities SET invalid_at = CURRENT_TIMESTAMP WHERE id = ? AND invalid_at IS NULL",
                (eid,))
    if affected:
        recompute_cooccurrence(conn, affected)


async def run_scan_source(job: dict, db_path: str) -> None:
    settings = get_settings()
    conn = get_connection(db_path)
    relay = Relay.from_settings(settings)

    config = json.loads(job["config"]) if job.get("config") else {}
    source_id = config.get("source_id") or job.get("target")

    ws = conn.execute("SELECT * FROM watched_sources WHERE id = ?", (source_id,)).fetchone()
    if ws is None:
        conn.close()
        raise ValueError(f"watched source not found: {source_id!r}")

    conn.execute("UPDATE watched_sources SET last_status = 'running' WHERE id = ?", (source_id,))
    conn.commit()

    try:
        featurizer = _resolve_featurizer(ws["type"])
        source_config = json.loads(ws["config_json"]) if ws["config_json"] else {}

        seen_paths: set[str] = set()
        actions = {"created": 0, "updated": 0, "skipped": 0, "conflict": 0}
        for source_path, title, content, emits in featurizer(ws["uri"], source_config):
            seen_paths.add(source_path)
            res = await upsert_document(
                conn, relay, settings, source_path=source_path, title=title,
                content=content, source_id=source_id, emits_cooccurrence=emits)
            actions[res["action"]] = actions.get(res["action"], 0) + 1

        # Deletion set: docs this source owns whose path is gone from the scan.
        owned = conn.execute(
            "SELECT id, source_path FROM documents WHERE source_id = ? AND invalid_at IS NULL",
            (source_id,)).fetchall()
        deleted = 0
        for row in owned:
            if row["source_path"] not in seen_paths:
                _soft_delete_document(conn, row["id"])
                deleted += 1

        mark_graph_dirty(conn)
        conn.execute(
            "UPDATE watched_sources SET last_scanned_at = CURRENT_TIMESTAMP, "
            "last_status = 'ok', last_error = NULL WHERE id = ?", (source_id,))
        conn.commit()
        print(f"[scan_source] {ws['type']} {ws['uri']}: {actions}, deleted {deleted}", flush=True)
    except Exception as e:  # noqa: BLE001 — record on the row, then re-raise for the job machinery
        conn.execute(
            "UPDATE watched_sources SET last_scanned_at = CURRENT_TIMESTAMP, "
            "last_status = 'error', last_error = ? WHERE id = ?", (str(e), source_id))
        conn.commit()
        conn.close()
        raise
    conn.close()
