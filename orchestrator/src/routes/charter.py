# ABOUTME: POST/GET /charter — a domain expert's declaration of their domain and rules.
# ABOUTME: Writes the domain row, alias merge-map rows, and an authored spec in one transaction.

import uuid
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..dependencies import get_auth_store, AuthStore
from ..models import CharterRequest

router = APIRouter()


@router.post("/charter", status_code=status.HTTP_201_CREATED)
async def create_charter(request: CharterRequest, response: Response,
                         auth: AuthStore = Depends(get_auth_store)):
    """Bind an expert's opinion into the pipeline.

    Three declarations, three existing slots:
      - the canonical domain path      -> `domains`, so the classifier sees it from document 1
      - the names that mean the same   -> `domain_merge_map`, checked FIRST by normalize_domain_label
      - the extraction rules           -> `specs` with source='authored'

    The domain row is written BEFORE the alias rows on purpose: `domain_merge_map.to_path`
    references `domains(path)`, and `normalize_domain_label` returns `to_path` without
    checking that the domain exists.
    """
    store = auth.store
    domain = request.domain.strip()
    if not domain:
        raise HTTPException(status_code=400, detail="domain must not be empty")
    if not request.spec.strip():
        raise HTTPException(status_code=400, detail="spec must not be empty")

    conn = store.conn

    # 1. Canonical domain row (created first — the alias rows point at it)
    if store.domains.get(domain) is None:
        parent_path = "/".join(domain.split("/")[:-1]) or None
        store.domains.create(str(uuid.uuid4()), domain, parent_path)

    # 2. Aliases. Both lookup paths normalise with .lower().strip(), so the stored key must
    # match or it will never resolve. A self-referential row is skipped.
    aliases_written = 0
    for alias in request.aliases:
        key = alias.lower().strip()
        if not key or key == domain.lower():
            continue
        conn.execute(
            "INSERT OR REPLACE INTO domain_merge_map (from_label, to_path) VALUES (?, ?)",
            (key, domain),
        )
        aliases_written += 1

    # 3. The authored spec
    version = store.specs.get_latest_version(domain) + 1
    store.specs.create(str(uuid.uuid4()), domain, version, request.spec, source="authored")

    # 4. Setting spec_version is what stops ingest.py from ever auto-queueing a
    # simmer_domain job over this domain — its guard is `spec_version IS NULL`. This is
    # how an authored spec is protected from being silently replaced.
    store.domains.update_spec_version(domain, version)

    conn.commit()
    # 201 + Location is the project convention for creation endpoints, locked in by
    # tests/test_rest_hygiene.py.
    response.headers["Location"] = f"/charter?domain={quote(domain, safe='')}"
    return {"domain": domain, "aliases_written": aliases_written, "spec_version": version}


@router.get("/charter")
async def get_charter(domain: str, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    spec = store.specs.get_for_domain(domain)
    if not spec or spec.source != "authored":
        raise HTTPException(status_code=404, detail=f"No charter for domain: {domain}")
    aliases = [r["from_label"] for r in store.conn.execute(
        "SELECT from_label FROM domain_merge_map WHERE to_path = ?", (domain,)).fetchall()]
    return {"domain": domain, "aliases": aliases,
            "spec": spec.spec_content, "spec_version": spec.version}
