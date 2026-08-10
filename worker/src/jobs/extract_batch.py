# ABOUTME: Batch extraction job runner — processes all docs in scope with a given spec.
# ABOUTME: Calls the extraction model per chunk and stores entities + co-occurrence edges.

import json
import uuid
from itertools import combinations
from orrery_relay import Relay
from ..db import get_connection, mark_graph_dirty
from ..config import get_settings
from ..identity_filter import is_identity_noise

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
    elif scope == "code_intent":
        # Phase 2 of collection ingest. Scoped by content_type rather than by
        # collection id because a single ingest enqueues one batch and the docs it
        # produced are exactly the unswept code_intent ones — and the `status`
        # predicate is what makes a re-run idempotent (already-extracted docs move
        # to 'extracted' and drop out of scope).
        docs = conn.execute(
            "SELECT id FROM documents WHERE content_type = 'code_intent' AND status = 'classified'"
        ).fetchall()
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

        # Identity context for the noise filter: a doc's own path/basename and the
        # name of the collection it came from are identity, not intent. LEFT JOINed
        # so an ordinary upload (no collection) simply yields empty strings and the
        # filter degrades to the file-extension rule.
        ident = conn.execute(
            "SELECT d.title, c.name FROM documents d "
            "LEFT JOIN document_collections dc ON dc.document_id = d.id "
            "LEFT JOIN collections c ON c.id = dc.collection_id "
            "WHERE d.id = ?",
            (doc_id,),
        ).fetchone()
        doc_path = (ident[0] or "") if ident else ""
        collection_name = (ident[1] or "") if ident else ""

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
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            # Past the raw JSON there is still no guarantee of shape: a flaky model
            # can return a bare list, or a null where the object was asked for.
            entities = parsed.get("entities", []) if isinstance(parsed, dict) else []
            if not isinstance(entities, list):
                entities = []

            for entity in entities:
                # Skip malformed entries rather than crashing the whole batch on one:
                # a bare string or a name-less object would raise on .get(...)/lower(),
                # and one bad element in one chunk would abandon every remaining doc.
                if not isinstance(entity, dict) or not isinstance(entity.get("name"), str):
                    continue
                name = entity["name"].lower().strip()
                etype = entity.get("type") if isinstance(entity.get("type"), str) else "Thing"
                if not name:
                    continue

                # Drop file-path / self-name entities before they enter the graph.
                # They co-occur with everything in their own document by construction,
                # so once stored they are permanent hub nodes joining unrelated areas.
                if is_identity_noise(name, doc_path=doc_path, collection_name=collection_name):
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

        # Co-occurrence is gated on the document's explicit `emits_cooccurrence` flag.
        # A root or group summary mentions everything beneath it, so its pairwise
        # co-occurrence is noise — it would connect every entity in a subtree to every
        # other. The reads already filter on this flag; without the same gate on the
        # WRITE side those edges are still stored, still counted in weights, and
        # reappear anywhere the filter is not threaded through.
        #
        # A document outside any collection has no row here and DOES emit, which is
        # the correct default for an ordinary upload.
        link = conn.execute(
            "SELECT emits_cooccurrence FROM document_collections WHERE document_id = ?",
            (doc_id,)).fetchone()
        emits = link is None or bool(link[0])

        if emits:
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

    # Normalization only has work when NEW entities were added: batch normalization
    # re-embeds the entity set, so a trailing no-op batch (every doc already swept)
    # would otherwise pay that cost to decide nothing. The graph still has to be
    # marked dirty whenever documents were touched, though — status and co-occurrence
    # changed even with no new entities — so the two conditions are separate.
    if new_entities > 0:
        from ..normalizer import run_batch_normalization
        norm_conn = get_connection(db_path)
        try:
            norm_results = run_batch_normalization(norm_conn)
            print(f"Normalization: {norm_results}", flush=True)
        except Exception as e:
            print(f"Normalization failed: {e}", flush=True)
        finally:
            # In the `finally` on purpose: a failed normalization still leaves the
            # extracted entities behind, so the graph has changed either way and a
            # clean-path-only flag would serve a stale snapshot until the next
            # unrelated write.
            mark_graph_dirty(norm_conn)
            norm_conn.commit()
            norm_conn.close()
    elif docs_processed > 0:
        norm_conn = get_connection(db_path)
        try:
            mark_graph_dirty(norm_conn)
            norm_conn.commit()
        finally:
            norm_conn.close()
        print(f"Normalization skipped: 0 new entities ({docs_processed} docs processed)", flush=True)
    else:
        print("Normalization skipped: no-op batch (0 docs, 0 new entities)", flush=True)
