"""Vocabulary-agnostic readers for the /graph payload.

The wire payload's vocabulary moves one group per ablation phase (see
docs/superpowers/specs/2026-08-05-graph-contract-design.md). Tests that only want
"the render set" or "the full node index" go through these, so a phase touches one
definition instead of every assertion.
"""


def render_entities(payload):
    """Entity records in the render set, degree-ranked. nodes[] in v5, `entities` in v4."""
    if "nodes" in payload:
        return [n for n in payload["nodes"] if n["type"] == "entity"]
    return payload.get("entities", [])


def node_index(payload):
    """id -> record for EVERY node. `node_index` in v5, `positions` in v4."""
    return payload.get("node_index", payload.get("positions", {}))


def entity_id(record):
    """Identity of an entity record in either vocabulary."""
    return record.get("id", record.get("entityId"))


def domain_weights(record):
    """Domain membership weights for an entity record, in either vocabulary.

    v5 collapses domainWeights + repoWeights into one `memberships` list tagged with
    container_type, so a third container kind needs no third map.
    """
    if "memberships" in record:
        return {m["id"]: m["weight"] for m in record["memberships"]
                if m["container_type"] == "domain"}
    return record.get("domainWeights", {})


def repo_weights(record):
    """Repo membership weights for an entity record, in either vocabulary."""
    if "memberships" in record:
        return {m["id"]: m["weight"] for m in record["memberships"]
                if m["container_type"] == "collection"}
    return record.get("repoWeights", {})


def render_repos(payload):
    """Repo records in v4 shape, read from either vocabulary.

    v5 has no separate `repos` key — repos are nodes[] entries of type='collection'.
    """
    if "nodes" in payload:
        return [{"id": n["id"], "name": n["label"], "path": n.get("path"),
                 "document_count": n.get("degree", 0),
                 "domain": next((m["id"] for m in n.get("memberships", [])
                                 if m["container_type"] == "domain"), None)}
                for n in payload["nodes"] if n["type"] == "collection"]
    return payload.get("collections", [])
