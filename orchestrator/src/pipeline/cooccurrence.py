from itertools import combinations
from collections import defaultdict
import uuid

def compute_cooccurrence_edges(chunk_entities: dict[str, list[str]]) -> list[dict]:
    pair_weight: dict[tuple[str, str], int] = defaultdict(int)
    pair_first_chunk: dict[tuple[str, str], str] = {}
    for chunk_id, entity_ids in chunk_entities.items():
        for a, b in combinations(sorted(set(entity_ids)), 2):
            pair = (a, b)
            pair_weight[pair] += 1
            if pair not in pair_first_chunk:
                pair_first_chunk[pair] = chunk_id
    edges = []
    for (a, b), weight in pair_weight.items():
        edges.append({"id": str(uuid.uuid4()), "from": a, "to": b, "type": "co_occurs", "weight": weight, "source_chunk": pair_first_chunk[(a, b)]})
    return edges
