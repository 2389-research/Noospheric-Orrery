from fastapi import APIRouter
from anthropic import AsyncAnthropicBedrock
from ..config import get_settings
from ..db import get_connection
from ..pipeline.subdomain_discovery import run_subdomain_discovery

router = APIRouter()


@router.post("/discover-subdomains")
async def trigger_subdomain_discovery():
    """Run subdomain discovery on all extracted docs."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )
    try:
        results = await run_subdomain_discovery(
            client=client,
            model=settings.classification_model,
            conn=conn,
        )
    finally:
        conn.close()
    return results
