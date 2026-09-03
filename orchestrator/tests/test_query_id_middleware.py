# ABOUTME: The API owns the query correlation id (issue #93) — every read returns a query_id
# ABOUTME: in the X-Query-Id header AND injected into the JSON body, for ANY caller (MCP/curl/SDK).

import re

_QID = re.compile(r"^qry_[0-9a-f]{32}$")


def test_read_response_carries_query_id_header_and_body(test_client):
    r = test_client.get("/stats")
    assert r.status_code == 200
    # header on every response
    assert _QID.match(r.headers.get("X-Query-Id", ""))
    # injected into the JSON dict body so a bare `curl` (no -i) still captures it
    body = r.json()
    assert isinstance(body, dict) and _QID.match(body.get("query_id", ""))
    # header and body agree
    assert body["query_id"] == r.headers["X-Query-Id"]


def test_each_call_gets_a_distinct_query_id(test_client):
    a = test_client.get("/stats").json()["query_id"]
    b = test_client.get("/stats").json()["query_id"]
    assert a != b


def test_list_response_still_gets_header(test_client, test_store):
    # /workspaces returns a JSON list — can't inject a top-level field, but the header carries it.
    r = test_client.get("/workspaces")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert _QID.match(r.headers.get("X-Query-Id", ""))
