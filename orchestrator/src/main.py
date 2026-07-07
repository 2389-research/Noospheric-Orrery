import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .db import init_db
from .repositories.factory import _sqlite_workspace_db_path

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run schema + migrations for the default noosphere up front so the first
    # request doesn't pay the cost (and doesn't collide with the worker).
    init_db(_sqlite_workspace_db_path("default"))
    # Also init any noospheres already in the registry so their first request
    # is a fast read instead of a write-locked migration.
    registry_path = os.path.join(
        os.path.dirname(get_settings().db_path), "workspaces", "registry.json"
    )
    registry: list[dict] = []
    try:
        import json
        if os.path.exists(registry_path):
            with open(registry_path) as f:
                registry = json.load(f)
    except Exception as e:
        # File missing or unparseable — skip warmup; lazy init still works.
        logger.warning("Noosphere registry unreadable (%s): %s", registry_path, e)
    for ws in registry:
        if ws.get("status") == "archived":
            continue
        ws_id = ws.get("id")
        if not ws_id:
            logger.warning("Skipping registry entry without id: %r", ws)
            continue
        try:
            init_db(_sqlite_workspace_db_path(ws_id))
        except Exception:
            # One bad noosphere shouldn't stop the others from being warmed.
            logger.warning("Noosphere warmup failed for %s", ws_id, exc_info=True)
    # Pre-warm SentenceTransformer model so first /graph request isn't slow
    try:
        from .pipeline.domain_layout import _embed_texts
        _embed_texts(["warmup"])
    except Exception:
        pass  # No embedding available — circular layout fallback
    yield

app = FastAPI(title="Noospheric Orrery", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routes.ingest import router as ingest_router
from .routes.documents import router as documents_router
from .routes.domains import router as domains_router
from .routes.entities import router as entities_router
from .routes.jobs import router as jobs_router
from .routes.simmer import router as simmer_router
from .routes.stats import router as stats_router
from .routes.normalize import router as normalize_router
from .routes.subdomains import router as subdomains_router
from .routes.graph import router as graph_router
from .routes.reader import router as reader_router
from .routes.search import router as search_router
from .routes.reclassify import router as reclassify_router
from .routes.auth_routes import router as auth_router
from .routes.workspace_routes import router as workspace_router
from .routes.image_files import router as image_files_router
from .routes.graph_ops import router as graph_ops_router
from .routes.corrections import router as corrections_router

app.include_router(ingest_router)
app.include_router(documents_router)
app.include_router(domains_router)
app.include_router(entities_router)
app.include_router(jobs_router)
app.include_router(simmer_router)
app.include_router(stats_router)
app.include_router(normalize_router)
app.include_router(subdomains_router)
app.include_router(graph_router)
app.include_router(reader_router)
app.include_router(search_router)
app.include_router(reclassify_router)
app.include_router(image_files_router)
app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(graph_ops_router)
app.include_router(corrections_router)

from fastapi import WebSocket as WS
from .broadcast import ws_endpoint

@app.websocket("/ws")
async def websocket_route(websocket: WS):
    await ws_endpoint(websocket)

@app.get("/health")
def health():
    return {"status": "ok"}
