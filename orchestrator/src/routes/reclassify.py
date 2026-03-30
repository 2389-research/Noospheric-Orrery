"""Reclassify existing documents with the current classifier prompt."""

from fastapi import APIRouter
from anthropic import AsyncAnthropicBedrock
from ..config import get_settings
from ..repositories.factory import get_store
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import normalize_domain_label

router = APIRouter()


@router.post("/reclassify")
async def reclassify_all():
    """Re-run classification on all documents. Adds new domains without removing existing ones."""
    settings = get_settings()
    store = get_store()
    conn = store.conn  # legacy access during migration
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )

    docs = conn.execute("SELECT id, title, content FROM documents ORDER BY created_at").fetchall()
    results = {"docs_processed": 0, "new_domains": [], "new_assignments": 0}

    for doc in docs:
        doc_id, title, content = doc[0], doc[1], doc[2]

        # Get existing assignments
        existing = set(r[0] for r in conn.execute(
            "SELECT domain_path FROM document_domains WHERE document_id = ?", (doc_id,)
        ).fetchall())

        # Get current taxonomy
        taxonomy = [r[0] for r in conn.execute("SELECT path FROM domains ORDER BY path").fetchall()]

        # Classify
        excerpt = build_classification_excerpt(title, content)
        try:
            classification = await classify_document(
                client=client, title=title, excerpt=excerpt,
                existing_taxonomy=taxonomy, model=settings.classification_model,
            )
        except Exception as e:
            print(f"  Skip {title}: {e}", flush=True)
            continue

        # Add new domain assignments (don't remove existing)
        all_domains = []
        primary = classification.get("primary_domain")
        if primary:
            all_domains.append(primary)
        for sec in classification.get("secondary_domains", []):
            all_domains.append(sec)

        for domain_path in all_domains:
            if domain_path not in existing:
                path = normalize_domain_label(conn, domain_path)
                conn.execute(
                    "INSERT OR IGNORE INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, 0.7)",
                    (doc_id, path),
                )
                conn.execute(
                    "UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (path,)
                )
                results["new_assignments"] += 1
                if path not in existing and path not in [d for d in results["new_domains"]]:
                    if path not in taxonomy:
                        results["new_domains"].append(path)

        results["docs_processed"] += 1
        print(f"  Reclassified {results['docs_processed']}/{len(docs)}: {title[:40]}", flush=True)

        import asyncio
        await asyncio.sleep(0.5)  # Rate limit

    conn.commit()
    store.close()
    return results
