"""The /graph payload must expose the repo layer alongside the existing domain layer.

Seeds two repos, one entity shared across a document in each repo (so
get_repo_routes yields a shared-entity edge), and one repo_edges row (a
DISTINCT manifest co-usage edge — both classes must ship). Also seeds a
document_domains row so the shared entity clears the existing domainWeights
gate and appears in the entities list, where it must carry repoWeights.
"""

from tests.graph_payload import render_entities, render_repos, repo_weights


def _seed(store):
    c = store.conn
    c.execute("INSERT INTO documents (id, title) VALUES ('d1', 'doc1')")
    c.execute("INSERT INTO documents (id, title) VALUES ('d2', 'doc2')")
    c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
              "VALUES ('d1', 'alpha', 1, 1.0)")
    c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
              "VALUES ('d2', 'alpha', 1, 1.0)")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'shared-thing', 'Concept')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd2')")

    store.collections.create("r1", "repo-one", "repo-one", "/collections/repo-one")
    store.collections.create("r2", "repo-two", "repo-two", "/collections/repo-two")
    store.collections.link_document("d1", "r1", role="leaf")
    store.collections.link_document("d2", "r2", role="leaf")

    # 'repo_uses' is what ingest_repo actually writes. This previously seeded
    # 'manifest_co_usage' — a value nothing in the codebase writes — and still passed,
    # because the builder discarded `type` and relabelled every row as "uses".
    c.execute("INSERT INTO collection_edges (source, target, type, weight) VALUES ('r1', 'r2', 'repo_uses', 2.0)")
    c.commit()


def test_graph_payload_includes_repo_layer(test_client, test_store):
    _seed(test_store)

    r = test_client.get("/graph")
    assert r.status_code == 200
    body = r.json()

    for key in ("nodes", "layout", "edges"):
        assert key in body, f"missing key: {key}"

    # repos are nodes[type='collection'] as of ablation phase 6
    collection_ids = {r["id"] for r in render_repos(body)}
    assert collection_ids == {"r1", "r2"}
    for repo in render_repos(body):
        assert {"id", "name", "path", "document_count", "domain"} <= repo.keys()
    # repos are binned by their docs' domain; both repo docs are in 'alpha'
    assert {r["domain"] for r in render_repos(body)} == {"alpha"}

    # repo coordinates moved into layout.positions alongside every other node type
    # (ablation phase 2); a repo is a positioned id that matches a repo node.
    repo_pos = {k: v for k, v in body["layout"]["positions"].items() if k in collection_ids}
    assert set(repo_pos) == {"r1", "r2"}
    for pos in repo_pos.values():
        assert 0.0 <= pos["x"] <= 1.0
        assert 0.0 <= pos["y"] <= 1.0

    # Both repo relations now live in the typed `edges` collection (ablation phase 4),
    # still DISTINCT: sharing an entity is `cooccurrence`+scope=repo, while a declared
    # manifest dependency is `uses`.
    def edges_of(type_, scope=None):
        return [{"source": e["source"], "target": e["target"], "weight": e["weight"]}
                for e in body["edges"]
                if e["type"] == type_ and (scope is None or e["scope"] == scope)]

    assert edges_of("cooccurrence", "collection") == [{"source": "r1", "target": "r2", "weight": 1}]
    assert edges_of("uses") == [{"source": "r1", "target": "r2", "weight": 2.0}]

    entities_with_weights = [e for e in render_entities(body) if (e.get("id") or e.get("entityId")) == "e1"]
    assert len(entities_with_weights) == 1
    e1 = entities_with_weights[0]
    # repoWeights folded into `memberships` tagged container_type='collection' (phase 5)
    assert repo_weights(e1) == {"r1": 0.5, "r2": 0.5}
