# ABOUTME: The API owns the query correlation id (issue #93). QueryIdMiddleware sets an
# ABOUTME: X-Query-Id header on EVERY response (never touching the body); the capture-relevant
# ABOUTME: READ routes additionally include `query_id` in their JSON body via the query_id dep.

import json
import re
import tempfile

from starlette.responses import FileResponse

from src.main import app

_QID = re.compile(r"^qry_[0-9a-f]{32}$")


# ── header on every response, body untouched by the middleware ──────────────────

def test_every_response_carries_the_header(test_client):
    r = test_client.get("/stats")
    assert r.status_code == 200
    assert _QID.match(r.headers.get("X-Query-Id", ""))


def test_middleware_does_not_inject_into_non_capture_bodies(test_client):
    # /stats is not a capture route — the middleware only sets the header, never rewrites bodies,
    # so no `query_id` key appears in a body that its route didn't add itself.
    assert "query_id" not in test_client.get("/stats").json()


def test_list_response_still_gets_header(test_client, test_store):
    r = test_client.get("/workspaces")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert _QID.match(r.headers.get("X-Query-Id", ""))


# ── capture routes include query_id in the BODY (via the route + dependency) ────

def test_capture_route_puts_query_id_in_body_matching_header(test_client, test_store):
    test_store.conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1','Widget','Concept')")
    test_store.conn.commit()
    r = test_client.get("/entities/e1")
    assert r.status_code == 200
    body = r.json()
    assert _QID.match(body.get("query_id", ""))          # in the JSON body (a bare curl logs it)
    assert body["query_id"] == r.headers["X-Query-Id"]   # header and body agree


def test_each_call_gets_a_distinct_query_id(test_client, test_store):
    test_store.conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1','Widget','Concept')")
    test_store.conn.commit()
    a = test_client.get("/entities/e1").json()["query_id"]
    b = test_client.get("/entities/e1").json()["query_id"]
    assert a != b


# ── file downloads are never mutated (the middleware doesn't touch bodies at all) ─

_NOTEBOOK = {"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {"note": "café ☕"}}
_NB_PATH = tempfile.NamedTemporaryFile(suffix=".ipynb", delete=False).name
with open(_NB_PATH, "w") as _f:
    json.dump(_NOTEBOOK, _f)
_NB_BYTES = open(_NB_PATH, "rb").read()


@app.get("/_qidtest_file")
def _qidtest_file():
    return FileResponse(_NB_PATH, media_type="application/json")


def test_file_download_is_byte_for_byte_intact(test_client):
    r = test_client.get("/_qidtest_file")
    assert r.status_code == 200
    assert _QID.match(r.headers.get("X-Query-Id", ""))   # header still set
    assert r.content == _NB_BYTES                          # not re-encoded
    assert "query_id" not in r.json()                      # not injected
