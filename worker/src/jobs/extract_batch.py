# ABOUTME: Batch extraction job runner — processes all docs in scope with a given spec.
# ABOUTME: Calls the extraction model per chunk and stores entities + co-occurrence edges.

import json
import uuid
from itertools import combinations
from orrery_relay import Relay
from ..db import get_connection, mark_graph_dirty
from ..config import get_settings

async def run_extract_batch(job: dict, db_path: str) -> None:
    settings = get_settings()
    conn = get_connection(db_path)
    relay = Relay.from_settings(settings)

    job_id = job["id"]
    config = json.loads(job["config"]) if job["config"] else {}
    spec_id = config.get("spec_id")
    scope = config.get("scope", "all_classified")

    spec_row = conn.execute("SELECT spec_content, version, domain_path FROM specs WHERE id = ?", (spec_id,)).fetchone()
    if not spec_row:
        conn.close()
        raise ValueError(f"Spec not found: {spec_id}")
    spec = spec_row[0]
    spec_version = spec_row[1]
    spec_domain = spec_row[2]
    spec_label = f"domain/{spec_domain}_v{spec_version}" if spec_domain else f"general_v{spec_version}"

    if scope == "all_classified":
        docs = conn.execute("SELECT id FROM documents WHERE status = 'classified'").fetchall()
    else:
        domain = config.get("domain")
        docs = conn.execute("""SELECT d.id FROM documents d
            JOIN document_domains dd ON d.id = dd.document_id WHERE dd.domain_path = ?""", (domain,)).fetchall()

    conn.close()

    # Track stats
    total_entities = 0
    new_entities = 0
    matched_entities = 0
    docs_processed = 0

    for doc_row in docs:
        doc_id = doc_row[0]
        conn = get_connection(db_path)
        chunks = conn.execute("SELECT id, text FROM chunks WHERE document_id = ? ORDER BY chunk_index", (doc_id,)).fetchall()

        chunk_entities: dict[str, list[str]] = {}

        for chunk in chunks:
            chunk_id, chunk_text = chunk[0], chunk[1]
            response = await relay.complete(
                model=settings.extraction_model, max_tokens=4096,
                messages=[{"role": "user", "content": f"{spec}\n\nTEXT:\n{chunk_text}\n\nRespond with JSON only: {{\"entities\": [{{\"name\": \"...\", \"type\": \"...\"}}]}}"}],
            )
            text = response.text
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            try:
                entities = json.loads(text).get("entities", [])
            except json.JSONDecodeError:
                continue

            for entity in entities:
                name = entity.get("name", "").lower().strip()
                etype = entity.get("type", "Thing")
                if not name:
                    continue

                is_new = False
                row = conn.execute("SELECT to_entity_id FROM merge_map WHERE from_name = ?", (name,)).fetchone()
                if row:
                    entity_id = row[0]
                else:
                    row = conn.execute("SELECT id FROM entities WHERE canonical_name = ? AND type = ?", (name, etype)).fetchone()
                    if row:
                        entity_id = row[0]
                    else:
                        entity_id = str(uuid.uuid4())
                        conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (entity_id, name, etype))
                        is_new = True

                extraction_pass = "domain-specific" if scope == "domain" else "general"
                conn.execute(
                    "INSERT INTO entity_sources (entity_id, document_id, chunk_id, extraction_pass, spec_version, job_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (entity_id, doc_id, chunk_id, extraction_pass, spec_version, job_id),
                )
                chunk_entities.setdefault(chunk_id, []).append(entity_id)

                total_entities += 1
                if is_new:
                    new_entities += 1
                else:
                    matched_entities += 1

        pair_counts: dict[tuple, int] = {}
        for cid, eids in chunk_entities.items():
            for a, b in combinations(sorted(set(eids)), 2):
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
        for (a, b), weight in pair_counts.items():
            conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight) VALUES (?, ?, ?, 'co_occurs', ?)",
                (str(uuid.uuid4()), a, b, weight))

        new_status = "enriched" if scope == "domain" else "extracted"
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", (new_status, doc_id))
        conn.commit()
        conn.close()
        docs_processed += 1
        print(f"  Extracted doc {docs_processed}/{len(docs)}: {total_entities} entities ({new_entities} new)", flush=True)

    # Store batch results summary on the job
    results_conn = get_connection(db_path)
    results_conn.execute(
        "UPDATE jobs SET result = ? WHERE id = ?",
        (json.dumps({
            "entities_found": total_entities,
            "entities_new": new_entities,
            "entities_matched": matched_entities,
            "docs_processed": docs_processed,
            "spec_version": spec_label,
        }), job_id),
    )
    results_conn.commit()
    results_conn.close()

    # Run normalization after all docs are extracted
    from ..normalizer import run_batch_normalization
    norm_conn = get_connection(db_path)
    try:
        norm_results = run_batch_normalization(norm_conn)
        print(f"Normalization: {norm_results}", flush=True)
    except Exception as e:
        print(f"Normalization failed: {e}", flush=True)
    finally:
        # New entities + co-occurrence edges (and any merges) changed the graph —
        # flag the snapshot for rebuild. In the `finally` on purpose: a failed
        # normalization still leaves the extracted entities behind, so the graph
        # has changed either way and a clean-path-only flag would serve a stale
        # snapshot until the next unrelated write.
        mark_graph_dirty(norm_conn)
        norm_conn.commit()
        norm_conn.close()
