from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    settings = get_settings()
    if os.environ.get("DB_BACKEND", "sqlite") == "sqlite":
        init_db(settings.db_path)
    # Pre-warm SentenceTransformer model so first /graph request isn't slow
    from .pipeline.domain_layout import _get_embed_model
    _get_embed_model()
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
app.include_router(auth_router)
app.include_router(workspace_router)

from fastapi import WebSocket as WS
from .broadcast import ws_endpoint

@app.websocket("/ws")
async def websocket_route(websocket: WS):
    await ws_endpoint(websocket)

@app.get("/health")
def health():
    return {"status": "ok"}
