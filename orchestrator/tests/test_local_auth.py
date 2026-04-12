"""Tests for local auth — no Firebase, always DEV_USER."""


def test_provision_returns_workspaces(test_client, test_store):
    """POST /auth/provision returns local workspace list."""
    resp = test_client.post("/auth/provision")
    assert resp.status_code == 200
    data = resp.json()
    assert data["orgId"] == "local"
    assert data["role"] == "admin"
    assert isinstance(data["workspaces"], list)


def test_workspace_crud(test_client, test_store):
    """Create, list, rename, archive workspaces."""
    # Create
    resp = test_client.post("/workspaces", json={"name": "Test WS"})
    assert resp.status_code == 200
    ws_id = resp.json()["workspaceId"]

    # List
    resp = test_client.get("/workspaces")
    assert resp.status_code == 200
    names = [w["name"] for w in resp.json()]
    assert "Test WS" in names

    # Rename
    resp = test_client.patch(f"/workspaces/{ws_id}", json={"name": "Renamed"})
    assert resp.status_code == 200

    # Archive
    resp = test_client.delete(f"/workspaces/{ws_id}")
    assert resp.status_code == 200

    # Should not appear in list
    resp = test_client.get("/workspaces")
    ids = [w["id"] for w in resp.json()]
    assert ws_id not in ids


def test_invite_stubs_return_ok(test_client, test_store):
    """Invite endpoints return stubs in local mode."""
    resp = test_client.post("/invites", json={"email": "test@test.com"})
    assert resp.status_code == 200

    resp = test_client.get("/invites")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = test_client.delete("/invites/any-id")
    assert resp.status_code == 200

    resp = test_client.post("/auth/accept-invite")
    assert resp.status_code == 200


def test_stats_includes_image_count(test_client, test_store):
    """GET /stats returns image_count."""
    resp = test_client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "image_count" in data
    assert data["image_count"] == 0


def test_health_endpoint(test_client):
    resp = test_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
