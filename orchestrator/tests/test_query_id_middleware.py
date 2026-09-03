# ABOUTME: The API owns the query correlation id (issue #93) — every read returns a query_id
# ABOUTME: in the X-Query-Id header AND injected into the JSON body, for ANY caller (MCP/curl/SDK).

import json
import re
import tempfile

from starlette.responses import FileResponse

from src.main import app

_QID = re.compile(r"^qry_[0-9a-f]{32}$")

# A JSON file served as a download — mirrors GET /documents/{id}/file for a .ipynb, which
# returns a FileResponse(media_type="application/json"). The middleware must NOT rewrite it.
_NOTEBOOK = {"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {"note": "café ☕"}}
_NB_PATH = tempfile.NamedTemporaryFile(suffix=".ipynb", delete=False).name
with open(_NB_PATH, "w") as _f:
    json.dump(_NOTEBOOK, _f)
_NB_BYTES = open(_NB_PATH, "rb").read()


@app.get("/_qidtest_file")
def _qidtest_file():
    return FileResponse(_NB_PATH, media_type="application/json")


def test_file_download_is_not_rewritten(test_client):
    r = test_client.get("/_qidtest_file")
    assert r.status_code == 200
    assert _QID.match(r.headers.get("X-Query-Id", ""))     # header still set
    assert r.content == _NB_BYTES                           # bytes byte-for-byte intact
    assert "query_id" not in r.json()                       # no injected key


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
