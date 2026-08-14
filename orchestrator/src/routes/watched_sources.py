# ABOUTME: CRUD for watched_sources — the registry of vaults/repos the worker re-syncs.
# ABOUTME: Thin rows: "which sources, at what cadence". The worker sweep does the scanning.
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..dependencies import get_auth_store, AuthStore

router = APIRouter()


class WatchedSourceCreate(BaseModel):
    type: str                      # 'vault' | 'repo'
    uri: str
    noosphere: str | None = None
    cadence_hours: float = 24
    config_json: dict | None = None


class WatchedSourcePatch(BaseModel):
    enabled: bool | None = None
    cadence_hours: float | None = None


def _to_dict(row) -> dict:
    d = {k: row[k] for k in row.keys()}
    if d.get("config_json"):
        try:
            d["config_json"] = json.loads(d["config_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


@router.post("/watched-sources")
def create_watched_source(body: WatchedSourceCreate, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    source_id = str(uuid.uuid4())
    store.conn.execute(
        "INSERT INTO watched_sources (id, type, uri, noosphere, cadence_hours, config_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source_id, body.type, body.uri, body.noosphere, body.cadence_hours,
         json.dumps(body.config_json) if body.config_json is not None else None),
    )
    store.conn.commit()
    row = store.conn.execute("SELECT * FROM watched_sources WHERE id = ?", (source_id,)).fetchone()
    store.close()
    return _to_dict(row)


@router.get("/watched-sources")
def list_watched_sources(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    rows = store.conn.execute(
        "SELECT * FROM watched_sources ORDER BY created_at DESC").fetchall()
    store.close()
    return [_to_dict(r) for r in rows]


@router.patch("/watched-sources/{source_id}")
def patch_watched_source(source_id: str, body: WatchedSourcePatch,
                         auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    if not store.conn.execute(
            "SELECT 1 FROM watched_sources WHERE id = ?", (source_id,)).fetchone():
        store.close()
        raise HTTPException(status_code=404, detail="watched source not found")

    sets, params = [], []
    if body.enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if body.enabled else 0)
    if body.cadence_hours is not None:
        sets.append("cadence_hours = ?")
        params.append(body.cadence_hours)
    if sets:
        params.append(source_id)
        store.conn.execute(
            f"UPDATE watched_sources SET {', '.join(sets)} WHERE id = ?", params)
        store.conn.commit()

    row = store.conn.execute("SELECT * FROM watched_sources WHERE id = ?", (source_id,)).fetchone()
    store.close()
    return _to_dict(row)
