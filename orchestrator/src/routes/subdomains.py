# ABOUTME: Subdomain discovery route — triggers additive subdomain tagging for all extracted docs.
# ABOUTME: Delegates to the subdomain_discovery pipeline with a Relay instance.

from fastapi import APIRouter
from orrery_relay import Relay
from ..config import get_settings
from ..db import get_connection
from ..pipeline.subdomain_discovery import run_subdomain_discovery

router = APIRouter()


@router.post("/discover-subdomains")
async def trigger_subdomain_discovery():
    """Run subdomain discovery on all extracted docs."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    relay = Relay.from_settings(settings)
    try:
        results = await run_subdomain_discovery(
            relay=relay,
            model=settings.classification_model,
            conn=conn,
        )
    finally:
        conn.close()
    return results
