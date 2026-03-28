from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.db_path)
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

app.include_router(ingest_router)
app.include_router(documents_router)
app.include_router(domains_router)
app.include_router(entities_router)
app.include_router(jobs_router)
app.include_router(simmer_router)
app.include_router(stats_router)
app.include_router(normalize_router)
app.include_router(subdomains_router)

@app.get("/health")
def health():
    return {"status": "ok"}
