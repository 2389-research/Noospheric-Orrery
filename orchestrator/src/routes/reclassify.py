"""Reclassify existing documents with the current classifier prompt."""

import asyncio
from fastapi import APIRouter, Depends
from anthropic import AsyncAnthropicBedrock
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import normalize_domain_label

router = APIRouter()


@router.post("/reclassify")
async def reclassify_all(auth: AuthStore = Depends(get_auth_store)):
    """Re-run classification on all documents. Adds new domains without removing existing ones."""
    settings = get_settings()
    store = auth.store
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )

    docs = store.documents.list(limit=10000)
    results = {"docs_processed": 0, "new_domains": [], "new_assignments": 0}

    for doc in docs:
        existing = set(d.domain_path for d in store.domains.get_domains_for_document(doc.id))
        taxonomy = store.domains.get_all_paths()

        excerpt = build_classification_excerpt(doc.title, doc.content or "")
        try:
            classification = await classify_document(
                client=client, title=doc.title, excerpt=excerpt,
                existing_taxonomy=taxonomy, model=settings.classification_model,
            )
        except Exception as e:
            print(f"  Skip {doc.title}: {e}", flush=True)
            continue

        all_domains = []
        primary = classification.get("primary_domain")
        if primary:
            all_domains.append(primary)
        for sec in classification.get("secondary_domains", []):
            all_domains.append(sec)

        for domain_path in all_domains:
            if domain_path not in existing:
                path = normalize_domain_label(store, domain_path)
                store.domains.assign_document(doc.id, path, False, 0.7)
                store.domains.increment_doc_count(path)
                results["new_assignments"] += 1
                if path not in existing and path not in results["new_domains"]:
                    if path not in taxonomy:
                        results["new_domains"].append(path)

        results["docs_processed"] += 1
        print(f"  Reclassified {results['docs_processed']}/{len(docs)}: {doc.title[:40]}", flush=True)
        await asyncio.sleep(0.5)

    store.close()
    return results
