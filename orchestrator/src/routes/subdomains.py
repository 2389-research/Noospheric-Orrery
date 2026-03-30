from fastapi import APIRouter
from anthropic import AsyncAnthropicBedrock
from ..config import get_settings
from ..repositories.factory import get_store
from ..pipeline.subdomain_discovery import run_subdomain_discovery

router = APIRouter()


@router.post("/discover-subdomains")
async def trigger_subdomain_discovery():
    settings = get_settings()
    store = get_store()
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )
    try:
        # Subdomain discovery still needs raw conn for complex queries
        if hasattr(store, 'conn'):
            results = await run_subdomain_discovery(
                client=client, model=settings.classification_model, conn=store.conn,
            )
        else:
            results = {"error": "Subdomain discovery not yet supported on Firestore"}
    finally:
        store.close()
    return results
