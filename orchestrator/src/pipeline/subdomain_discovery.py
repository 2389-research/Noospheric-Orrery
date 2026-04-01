# ABOUTME: Lightweight subdomain discovery from extracted entities.
# ABOUTME: Additive — docs gain subdomains, never lose existing domains.

import json
import sqlite3
from orrery_relay import Relay

SUBDOMAIN_PROMPT = """You are refining the domain taxonomy for a knowledge graph. A document has already been classified into these domains:

Current domains: {current_domains}

The document has these extracted entities:
{entities}

The existing taxonomy has these domains:
{taxonomy}

Based on the entity profile, should this document be tagged with any MORE SPECIFIC subdomains? Only propose subdomains that are clearly warranted by the entities.

Rules:
- Only ADD subdomains — never remove existing domain assignments
- Subdomains must be children of existing domains (e.g., business/fundraising → business/fundraising/seed_round)
- Only propose if the entities clearly indicate a specific subtopic
- If no subdomains are warranted, return an empty list

Respond with JSON only:
{{
    "new_subdomains": ["domain/path/subdomain", ...]
}}
"""


async def discover_subdomains_for_document(
    relay: Relay,
    model: str,
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Check if a doc should get more specific subdomains based on its entities."""

    # Get current domains
    current = conn.execute(
        "SELECT domain_path FROM document_domains WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    current_domains = [r[0] for r in current]

    if not current_domains:
        return []

    # Get extracted entities for this doc
    entities = conn.execute(
        """SELECT DISTINCT e.canonical_name, e.type FROM entities e
           JOIN entity_sources es ON e.id = es.entity_id
           WHERE es.document_id = ?""",
        (document_id,),
    ).fetchall()

    if len(entities) < 3:
        return []  # Not enough entities to discover subdomains

    entities_str = "\n".join(f"- {e[0]} ({e[1]})" for e in entities)

    # Get existing taxonomy
    taxonomy = conn.execute("SELECT path FROM domains ORDER BY path").fetchall()
    taxonomy_str = "\n".join(f"- {t[0]}" for t in taxonomy)

    response = await relay.complete(
        model=model,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": SUBDOMAIN_PROMPT.format(
                current_domains=", ".join(current_domains),
                entities=entities_str,
                taxonomy=taxonomy_str,
            ),
        }],
    )

    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
        return result.get("new_subdomains", [])
    except json.JSONDecodeError:
        return []


async def run_subdomain_discovery(
    relay: Relay,
    model: str,
    conn: sqlite3.Connection,
    document_ids: list[str] | None = None,
) -> dict:
    """Run subdomain discovery on docs. Returns summary."""
    import uuid
    from .domain_normalizer import normalize_domain_label

    if document_ids is None:
        # Run on all extracted docs
        rows = conn.execute(
            "SELECT id FROM documents WHERE status IN ('extracted', 'enriched')"
        ).fetchall()
        document_ids = [r[0] for r in rows]

    import asyncio

    results = {"docs_checked": 0, "subdomains_added": 0, "new_subdomains": []}

    for doc_id in document_ids:
        if results["docs_checked"] > 0:
            await asyncio.sleep(1)  # Rate limit protection
        new_subs = await discover_subdomains_for_document(relay, model, conn, doc_id)
        results["docs_checked"] += 1

        for sub_path in new_subs:
            # Normalize and create the subdomain
            path = normalize_domain_label(conn, sub_path)

            # Check if already assigned
            existing = conn.execute(
                "SELECT 1 FROM document_domains WHERE document_id = ? AND domain_path = ?",
                (doc_id, path),
            ).fetchone()

            if not existing:
                conn.execute(
                    "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, 0.6)",
                    (doc_id, path),
                )
                conn.execute(
                    "UPDATE domains SET document_count = document_count + 1 WHERE path = ?",
                    (path,),
                )
                results["subdomains_added"] += 1
                if path not in results["new_subdomains"]:
                    results["new_subdomains"].append(path)

    conn.commit()
    return results
