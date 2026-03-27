import json
import uuid
from itertools import combinations
from anthropic import AsyncAnthropicBedrock
from ..db import get_connection
from ..config import get_settings

async def run_extract_batch(job: dict, db_path: str) -> None:
    settings = get_settings()
    conn = get_connection(db_path)
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )

    config = json.loads(job["config"]) if job["config"] else {}
    spec_id = config.get("spec_id")
    scope = config.get("scope", "all_classified")

    spec_row = conn.execute("SELECT spec_content FROM specs WHERE id = ?", (spec_id,)).fetchone()
    if not spec_row:
        conn.close()
        raise ValueError(f"Spec not found: {spec_id}")
    spec = spec_row[0]

    if scope == "all_classified":
        docs = conn.execute("SELECT id FROM documents WHERE status = 'classified'").fetchall()
    else:
        domain = config.get("domain")
        docs = conn.execute("""SELECT d.id FROM documents d
            JOIN document_domains dd ON d.id = dd.document_id WHERE dd.domain_path = ?""", (domain,)).fetchall()

    conn.close()

    for doc_row in docs:
        doc_id = doc_row[0]
        conn = get_connection(db_path)
        chunks = conn.execute("SELECT id, text FROM chunks WHERE document_id = ? ORDER BY chunk_index", (doc_id,)).fetchall()

        chunk_entities: dict[str, list[str]] = {}

        for chunk in chunks:
            chunk_id, chunk_text = chunk[0], chunk[1]
            response = await client.messages.create(
                model=settings.extraction_model, max_tokens=4096,
                messages=[{"role": "user", "content": f"{spec}\n\nTEXT:\n{chunk_text}\n\nRespond with JSON only: {{\"entities\": [{{\"name\": \"...\", \"type\": \"...\"}}]}}"}],
            )
            text = response.content[0].text
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
                conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id, extraction_pass) VALUES (?, ?, ?, 'general')", (entity_id, doc_id, chunk_id))
                chunk_entities.setdefault(chunk_id, []).append(entity_id)

        pair_counts: dict[tuple, int] = {}
        for cid, eids in chunk_entities.items():
            for a, b in combinations(sorted(set(eids)), 2):
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
        for (a, b), weight in pair_counts.items():
            conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight) VALUES (?, ?, ?, 'co_occurs', ?)",
                (str(uuid.uuid4()), a, b, weight))

        conn.execute("UPDATE documents SET status = 'extracted' WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()

    # Run normalization after all docs are extracted
    from ..normalizer import run_batch_normalization
    norm_conn = get_connection(db_path)
    try:
        results = run_batch_normalization(norm_conn)
        print(f"Normalization: {results}", flush=True)
    except Exception as e:
        print(f"Normalization failed: {e}", flush=True)
    finally:
        norm_conn.close()
