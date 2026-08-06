# ABOUTME: Concept explorer — resolve → traverse cooccurrences + domains → synthesize.
# ABOUTME: Turns a search query into 3 gap/tension concepts, not restated facts. See docs/concept-explorer/README.md.

import sqlite3
from orrery_relay import Relay

MAX_ENTITIES = 5
COOCCURRENCE_LIMIT = 15
MIN_SHARED_DOCUMENTS = 2  # neighbors confined to 1 shared doc are same-paper coincidences, not cross-doc signal

CONCEPT_PROMPT = """You are exploring a knowledge graph built from a codebase/document corpus. \
A user searched for: "{query}"

These are the top-matching entities, the domains their sources belong to, and their \
1-hop neighbors in the graph (weight = co-occurrence strength). Every neighbor listed \
co-occurs with its entity across at least {min_shared_docs} distinct source documents — \
same-document-only coincidences have already been filtered out, since those would just \
restate one paper's content rather than surface a real cross-document gap:

{entity_neighborhoods}

Propose exactly 3 concepts worth exploring next. Each concept must be a TENSION, GAP, \
or OPEN QUESTION implied by the entities, domains, and neighbors above — not a tool, \
library, or entity name restated. Look for:
- a parameter/config that differs between two contexts implied by the domains/neighbors
- a metric or capability that co-occurs but whose failure modes aren't explained
- the same entity/domain reappearing across otherwise-separate neighborhoods

For each concept give a short name (a few words) and one sentence citing the specific \
entities or domains that suggested it.
"""

CONCEPT_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short concept name, not a tool/entity name"},
                    "evidence": {"type": "string", "description": "One sentence citing the specific entities/domains that suggested it"},
                },
                "required": ["name", "evidence"],
            },
        },
    },
    "required": ["concepts"],
}


def _domains_for_entity(conn: sqlite3.Connection, entity_id: str) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT dd.domain_path FROM entity_sources es
           JOIN document_domains dd ON dd.document_id = es.document_id
           WHERE es.entity_id = ?""",
        (entity_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _shared_document_count(conn: sqlite3.Connection, entity_a: str, entity_b: str) -> int:
    """How many distinct documents mention BOTH entities. A neighbor confined to a
    single shared document is a same-paper coincidence, not a cross-document signal —
    it can't ground a gap/tension (the whole point of concept exploration)."""
    row = conn.execute(
        """SELECT COUNT(DISTINCT esa.document_id) FROM entity_sources esa
           JOIN entity_sources esb ON esb.document_id = esa.document_id
           WHERE esa.entity_id = ? AND esb.entity_id = ?""",
        (entity_a, entity_b),
    ).fetchone()
    return row[0] if row else 0


async def explore_concepts(
    relay: Relay,
    model: str,
    conn: sqlite3.Connection,
    store,
    query: str,
    top_k: int = 20,
) -> dict:
    """Resolve a query to entities, traverse their cooccurrence neighborhoods and
    domains, and synthesize 3 gap/tension concepts."""
    from .search import search_knowledge_graph

    result = await search_knowledge_graph(conn, query, expand=False, relay=relay, top_k=top_k)

    top_entities = result.entities[:MAX_ENTITIES]
    if not top_entities:
        return {"query": query, "concepts": []}

    neighborhood_lines = []
    for e in top_entities:
        coentities = store.relationships.get_cooccurrences(e["id"], limit=COOCCURRENCE_LIMIT * 3)
        cross_doc_neighbors = [
            c for c in coentities
            if _shared_document_count(conn, e["id"], c.id) >= MIN_SHARED_DOCUMENTS
        ][:COOCCURRENCE_LIMIT]
        neighbors_str = ", ".join(f"{c.canonical_name} ({c.type}, w={c.weight})" for c in cross_doc_neighbors)
        domains = _domains_for_entity(conn, e["id"])
        domains_str = ", ".join(domains) if domains else "none"
        neighborhood_lines.append(
            f"- {e['name']} ({e['type']}) | domains: {domains_str} | neighbors: {neighbors_str or 'none (all candidates were single-document coincidences)'}"
        )
    entity_neighborhoods = "\n".join(neighborhood_lines)

    parsed = await relay.complete_structured(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": CONCEPT_PROMPT.format(
                query=query, entity_neighborhoods=entity_neighborhoods,
                min_shared_docs=MIN_SHARED_DOCUMENTS,
            ),
        }],
        schema=CONCEPT_SCHEMA,
        tool_name="propose_concepts",
        tool_description="Propose 3 gap/tension concepts implied by the entity/domain neighborhood",
    )

    return {"query": query, "concepts": parsed.get("concepts", [])}
