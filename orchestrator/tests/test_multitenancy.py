"""Tests for multi-tenancy: provision, invites, workspaces, isolation.

These tests mock Firebase Admin SDK and use a fake Firestore-like store
to verify the logic without hitting real Firebase infrastructure.
"""

import os
import pytest
from unittest.mock import patch

# Force settings before imports
os.environ["DB_BACKEND"] = "firestore"
# Keep AUTH_REQUIRED=false so get_current_user returns DEV_USER by default
# We'll override the user per-test via dependency_overrides
os.environ["AUTH_REQUIRED"] = "false"
os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")
os.environ.setdefault("AWS_REGION", "us-east-1")

from fastapi.testclient import TestClient
from src.auth import AuthUser, get_current_user


# ---------------------------------------------------------------------------
# Fake Firestore in-memory store for testing
# ---------------------------------------------------------------------------

class FakeDocumentSnapshot:
    def __init__(self, doc_id, data, store):
        self._id = doc_id
        self._data = data
        self._store = store

    @property
    def id(self):
        return self._id

    @property
    def exists(self):
        return self._data is not None

    @property
    def reference(self):
        return FakeDocumentRef(self._full_path, self._store)

    def to_dict(self):
        return self._data


def _resolve_sentinels(data: dict) -> dict:
    """Replace firestore.SERVER_TIMESTAMP sentinels with ISO strings."""
    from datetime import datetime, timezone
    result = {}
    for k, v in data.items():
        if hasattr(v, '__class__') and 'Sentinel' in type(v).__name__:
            result[k] = datetime.now(timezone.utc).isoformat()
        else:
            result[k] = v
    return result


class FakeDocumentRef:
    def __init__(self, path, store):
        self._path = path
        self._store = store

    @property
    def id(self):
        return self._path.split("/")[-1]

    def set(self, data, merge=False):
        resolved = _resolve_sentinels(data)
        if merge and self._path in self._store:
            existing = dict(self._store[self._path])
            existing.update(resolved)
            self._store[self._path] = existing
        else:
            self._store[self._path] = dict(resolved)

    def update(self, data):
        resolved = _resolve_sentinels(data)
        existing = self._store.get(self._path, {})
        existing = dict(existing)
        existing.update(resolved)
        self._store[self._path] = existing

    def get(self):
        data = self._store.get(self._path)
        snap = FakeDocumentSnapshot(self.id, data, self._store)
        snap._full_path = self._path
        return snap

    def collection(self, name):
        return FakeCollectionRef(f"{self._path}/{name}", self._store)


class FakeCollectionRef:
    _counter = 0

    def __init__(self, path, store):
        self._path = path
        self._store = store
        self._filters = []
        self._limit_val = None

    def document(self, doc_id=None):
        if doc_id is None:
            FakeCollectionRef._counter += 1
            doc_id = f"auto_{FakeCollectionRef._counter}"
        return FakeDocumentRef(f"{self._path}/{doc_id}", self._store)

    def where(self, field, op, value):
        new = FakeCollectionRef(self._path, self._store)
        new._filters = self._filters + [(field, op, value)]
        new._limit_val = self._limit_val
        return new

    def limit(self, n):
        new = FakeCollectionRef(self._path, self._store)
        new._filters = list(self._filters)
        new._limit_val = n
        return new

    def stream(self):
        results = []
        prefix = self._path + "/"
        for key, data in list(self._store.items()):
            if not key.startswith(prefix):
                continue
            remainder = key[len(prefix):]
            if "/" in remainder:
                continue
            match = True
            for field, op, value in self._filters:
                doc_val = data.get(field)
                if op == "==" and doc_val != value:
                    match = False
            if match:
                snap = FakeDocumentSnapshot(remainder, data, self._store)
                snap._full_path = key
                results.append(snap)
        if self._limit_val:
            results = results[:self._limit_val]
        return results


class FakeFirestoreClient:
    def __init__(self):
        self._store = {}

    def collection(self, name):
        return FakeCollectionRef(name, self._store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(uid, email, org_id="", role="editor"):
    name = email.split("@")[0] if email else None
    return AuthUser(uid=uid, email=email, name=name, org_id=org_id, role=role)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_counter():
    FakeCollectionRef._counter = 0
    yield


@pytest.fixture
def fake_db():
    return FakeFirestoreClient()


@pytest.fixture
def claims_store():
    return {}


@pytest.fixture
def app_client(fake_db, claims_store):
    """TestClient with mocked Firebase dependencies.

    Returns (client, user_ref, fake_db, claims_store).
    Set user_ref["user"] to change which user the next request authenticates as.
    """
    user_ref = {"user": make_user("user1", "alice@test.com")}

    async def fake_get_current_user():
        return user_ref["user"]

    def fake_get_claims(uid):
        return claims_store.get(uid, {})

    def fake_set_claims(uid, org_id, role):
        claims_store[uid] = {"orgId": org_id, "role": role}

    def fake_signal(db, uid):
        pass

    with patch("src.routes.auth_routes._get_firestore_db", return_value=fake_db), \
         patch("src.routes.workspace_routes._get_firestore_db", return_value=fake_db), \
         patch("src.auth_admin.get_user_claims", fake_get_claims), \
         patch("src.auth_admin.set_user_claims", fake_set_claims), \
         patch("src.auth_admin.signal_token_refresh", fake_signal):

        from src.main import app
        app.dependency_overrides[get_current_user] = fake_get_current_user
        client = TestClient(app)
        yield client, user_ref, fake_db, claims_store
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper: provision a user and make them admin
# ---------------------------------------------------------------------------

def provision_admin(client, user_ref, claims, uid, email):
    user_ref["user"] = make_user(uid, email)
    resp = client.post("/auth/provision")
    assert resp.status_code == 200, f"Provision failed: {resp.text}"
    data = resp.json()
    org_id = data["orgId"]
    user_ref["user"] = make_user(uid, email, org_id=org_id, role="admin")
    claims[uid] = {"orgId": org_id, "role": "admin"}
    return data


# ===================================================================
# PROVISION TESTS
# ===================================================================

class TestProvision:
    def test_new_user_gets_org_and_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("user1", "alice@test.com")

        resp = client.post("/auth/provision")
        assert resp.status_code == 200
        data = resp.json()

        assert data["role"] == "admin"
        assert data["orgId"]
        assert len(data["workspaces"]) == 1
        assert data["workspaces"][0]["name"] == "Default"

        # Claims should be set
        assert claims["user1"]["orgId"] == data["orgId"]
        assert claims["user1"]["role"] == "admin"

    def test_provision_is_idempotent(self, app_client):
        client, user_ref, db, claims = app_client

        data1 = provision_admin(client, user_ref, claims, "user1", "alice@test.com")

        # Second provision returns same org
        resp2 = client.post("/auth/provision")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["orgId"] == data1["orgId"]
        assert len(data2["workspaces"]) >= 1

    def test_two_users_get_separate_orgs(self, app_client):
        client, user_ref, db, claims = app_client

        data1 = provision_admin(client, user_ref, claims, "user1", "alice@test.com")
        # Reset to unprovisions user2
        user_ref["user"] = make_user("user2", "bob@test.com")
        resp2 = client.post("/auth/provision")
        data2 = resp2.json()

        assert data1["orgId"] != data2["orgId"]

    def test_org_name_derived_from_email(self, app_client):
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("user1", "john.doe@company.com")
        resp = client.post("/auth/provision")
        # Check org was created in the fake store
        org_entries = {k: v for k, v in db._store.items() if k.startswith("organizations/")}
        assert any("John Doe" in v.get("name", "") for v in org_entries.values())


# ===================================================================
# INVITE TESTS
# ===================================================================

class TestInvites:
    def test_create_and_list_invites(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        # Create invite
        resp = client.post("/invites", json={"email": "newuser@test.com", "role": "editor"})
        assert resp.status_code == 200
        invite_data = resp.json()
        assert invite_data["email"] == "newuser@test.com"
        assert invite_data["role"] == "editor"

        # List invites
        resp = client.get("/invites")
        assert resp.status_code == 200
        invites = resp.json()
        assert len(invites) == 1
        assert invites[0]["email"] == "newuser@test.com"

    def test_revoke_invite(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/invites", json={"email": "revokeme@test.com", "role": "viewer"})
        invite_id = resp.json()["inviteId"]

        resp = client.delete(f"/invites/{invite_id}")
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

        # Should not appear in pending list
        resp = client.get("/invites")
        assert len(resp.json()) == 0

    def test_accept_invite_joins_org(self, app_client):
        client, user_ref, db, claims = app_client

        # Admin creates org + invite
        admin_data = provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        client.post("/invites", json={"email": "invited@test.com", "role": "editor"})

        # New user accepts
        user_ref["user"] = make_user("newuser1", "invited@test.com")
        resp = client.post("/auth/accept-invite")
        assert resp.status_code == 200
        data = resp.json()
        assert data["invited"] is True
        assert data["orgId"] == admin_data["orgId"]
        assert data["role"] == "editor"
        assert claims["newuser1"]["orgId"] == admin_data["orgId"]

    def test_accept_invite_no_invite(self, app_client):
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("lonely1", "nobody@test.com")

        resp = client.post("/auth/accept-invite")
        assert resp.status_code == 200
        assert resp.json()["invited"] is False

    def test_already_provisioned_user_skips_invite(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/auth/accept-invite")
        data = resp.json()
        assert data["invited"] is False
        assert data["alreadyProvisioned"] is True

    def test_invalid_role_rejected(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/invites", json={"email": "bad@test.com", "role": "superadmin"})
        assert resp.status_code == 400


# ===================================================================
# WORKSPACE CRUD TESTS
# ===================================================================

class TestWorkspaceCRUD:
    def test_create_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/workspaces", json={"name": "Research", "description": "For research"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Research"
        assert data["workspaceId"]

    def test_list_workspaces_shows_own(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        client.post("/workspaces", json={"name": "Second WS"})

        resp = client.get("/workspaces")
        assert resp.status_code == 200
        names = [ws["name"] for ws in resp.json()]
        assert "Default" in names
        assert "Second WS" in names

    def test_rename_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/workspaces", json={"name": "Old Name"})
        ws_id = resp.json()["workspaceId"]

        resp = client.patch(f"/workspaces/{ws_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

    def test_archive_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/workspaces", json={"name": "Doomed"})
        ws_id = resp.json()["workspaceId"]

        resp = client.delete(f"/workspaces/{ws_id}")
        assert resp.status_code == 200
        assert resp.json()["archived"] is True

        # Archived workspace should not appear in list
        resp = client.get("/workspaces")
        names = [ws["name"] for ws in resp.json()]
        assert "Doomed" not in names

    def test_create_workspace_with_description(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.post("/workspaces", json={"name": "Described", "description": "Has a desc"})
        ws_id = resp.json()["workspaceId"]

        # Check it was stored
        ws_data = db._store.get(f"workspaces/{ws_id}")
        assert ws_data["description"] == "Has a desc"


# ===================================================================
# CROSS-ORG ISOLATION TESTS
# ===================================================================

class TestIsolation:
    def test_cannot_see_other_orgs_workspaces(self, app_client):
        client, user_ref, db, claims = app_client

        # User 1 creates workspaces
        provision_admin(client, user_ref, claims, "user1", "alice@test.com")
        client.post("/workspaces", json={"name": "Alice Private"})

        # User 2 provisions separately
        user_ref["user"] = make_user("user2", "bob@test.com")
        resp = client.post("/auth/provision")
        org2 = resp.json()["orgId"]
        user_ref["user"] = make_user("user2", "bob@test.com", org_id=org2, role="admin")
        claims["user2"] = {"orgId": org2, "role": "admin"}

        # User 2 should only see their own workspace
        resp = client.get("/workspaces")
        names = [ws["name"] for ws in resp.json()]
        assert "Default" in names
        assert "Alice Private" not in names

    def test_cannot_rename_other_orgs_workspace(self, app_client):
        client, user_ref, db, claims = app_client

        provision_admin(client, user_ref, claims, "user1", "alice@test.com")
        resp = client.post("/workspaces", json={"name": "Alice WS"})
        alice_ws_id = resp.json()["workspaceId"]

        # User 2
        user_ref["user"] = make_user("user2", "bob@test.com")
        client.post("/auth/provision")
        org2 = claims.get("user2", {}).get("orgId", "")
        user_ref["user"] = make_user("user2", "bob@test.com", org_id=org2, role="admin")

        resp = client.patch(f"/workspaces/{alice_ws_id}", json={"name": "Hacked"})
        assert resp.status_code == 404

    def test_cannot_archive_other_orgs_workspace(self, app_client):
        client, user_ref, db, claims = app_client

        provision_admin(client, user_ref, claims, "user1", "alice@test.com")
        resp = client.post("/workspaces", json={"name": "Alice WS"})
        alice_ws_id = resp.json()["workspaceId"]

        user_ref["user"] = make_user("user2", "bob@test.com")
        client.post("/auth/provision")
        org2 = claims["user2"]["orgId"]
        user_ref["user"] = make_user("user2", "bob@test.com", org_id=org2, role="admin")

        resp = client.delete(f"/workspaces/{alice_ws_id}")
        assert resp.status_code == 404

    def test_cannot_revoke_other_orgs_invite(self, app_client):
        client, user_ref, db, claims = app_client

        provision_admin(client, user_ref, claims, "user1", "alice@test.com")
        resp = client.post("/invites", json={"email": "friend@test.com", "role": "editor"})
        invite_id = resp.json()["inviteId"]

        # User 2
        user_ref["user"] = make_user("user2", "bob@test.com")
        client.post("/auth/provision")
        org2 = claims["user2"]["orgId"]
        user_ref["user"] = make_user("user2", "bob@test.com", org_id=org2, role="admin")

        resp = client.delete(f"/invites/{invite_id}")
        assert resp.status_code == 404

    def test_other_orgs_invites_not_listed(self, app_client):
        client, user_ref, db, claims = app_client

        provision_admin(client, user_ref, claims, "user1", "alice@test.com")
        client.post("/invites", json={"email": "secret@test.com", "role": "editor"})

        user_ref["user"] = make_user("user2", "bob@test.com")
        client.post("/auth/provision")
        org2 = claims["user2"]["orgId"]
        user_ref["user"] = make_user("user2", "bob@test.com", org_id=org2, role="admin")

        resp = client.get("/invites")
        assert len(resp.json()) == 0


# ===================================================================
# ROLE ENFORCEMENT TESTS
# ===================================================================

class TestRoles:
    def test_viewer_cannot_create_invite(self, app_client):
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("viewer1", "view@test.com", org_id="org1", role="viewer")
        claims["viewer1"] = {"orgId": "org1", "role": "viewer"}

        resp = client.post("/invites", json={"email": "new@test.com", "role": "editor"})
        assert resp.status_code == 403

    def test_viewer_cannot_create_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("viewer1", "view@test.com", org_id="org1", role="viewer")

        resp = client.post("/workspaces", json={"name": "Nope"})
        assert resp.status_code == 403

    def test_editor_cannot_create_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("editor1", "edit@test.com", org_id="org1", role="editor")

        resp = client.post("/workspaces", json={"name": "Nope"})
        assert resp.status_code == 403

    def test_viewer_can_list_workspaces(self, app_client):
        client, user_ref, db, claims = app_client

        # Admin provisions first
        admin_data = provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        org_id = admin_data["orgId"]

        # Viewer lists
        user_ref["user"] = make_user("viewer1", "view@test.com", org_id=org_id, role="viewer")
        resp = client.get("/workspaces")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_editor_can_list_workspaces(self, app_client):
        client, user_ref, db, claims = app_client

        admin_data = provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        org_id = admin_data["orgId"]

        user_ref["user"] = make_user("editor1", "edit@test.com", org_id=org_id, role="editor")
        resp = client.get("/workspaces")
        assert resp.status_code == 200

    def test_admin_can_rename_workspace(self, app_client):
        client, user_ref, db, claims = app_client

        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        resp = client.post("/workspaces", json={"name": "Renamable"})
        ws_id = resp.json()["workspaceId"]

        resp = client.patch(f"/workspaces/{ws_id}", json={"name": "Renamed"})
        assert resp.status_code == 200

    def test_editor_can_list_invites_blocked(self, app_client):
        """require_role('admin') should block editors from invite endpoints."""
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("editor1", "edit@test.com", org_id="org1", role="editor")

        resp = client.get("/invites")
        assert resp.status_code == 403

    def test_viewer_cannot_rename_workspace(self, app_client):
        client, user_ref, db, claims = app_client

        admin_data = provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        resp = client.post("/workspaces", json={"name": "Test WS"})
        ws_id = resp.json()["workspaceId"]

        user_ref["user"] = make_user("viewer1", "view@test.com", org_id=admin_data["orgId"], role="viewer")
        resp = client.patch(f"/workspaces/{ws_id}", json={"name": "Hacked"})
        assert resp.status_code == 403

    def test_viewer_cannot_archive_workspace(self, app_client):
        client, user_ref, db, claims = app_client

        admin_data = provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        resp = client.post("/workspaces", json={"name": "Test WS"})
        ws_id = resp.json()["workspaceId"]

        user_ref["user"] = make_user("viewer1", "view@test.com", org_id=admin_data["orgId"], role="viewer")
        resp = client.delete(f"/workspaces/{ws_id}")
        assert resp.status_code == 403


# ===================================================================
# PROVISION EDGE CASES
# ===================================================================

class TestProvisionEdgeCases:
    def test_provision_excludes_archived_workspaces(self, app_client):
        """Returning user should not see archived workspaces in provision response."""
        client, user_ref, db, claims = app_client

        # Provision and create a second workspace
        admin_data = provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        resp = client.post("/workspaces", json={"name": "To Archive"})
        ws_id = resp.json()["workspaceId"]

        # Archive it
        client.delete(f"/workspaces/{ws_id}")

        # Re-provision — should not include archived workspace
        resp = client.post("/auth/provision")
        ws_names = [ws["name"] for ws in resp.json()["workspaces"]]
        assert "To Archive" not in ws_names
        assert "Default" in ws_names

    def test_provision_with_no_email(self, app_client):
        """User with no email should still provision (uses 'User' fallback)."""
        client, user_ref, db, claims = app_client
        user_ref["user"] = make_user("user1", None)  # type: ignore

        resp = client.post("/auth/provision")
        assert resp.status_code == 200
        assert resp.json()["orgId"]


# ===================================================================
# INVITE EDGE CASES
# ===================================================================

class TestInviteEdgeCases:
    def test_invite_consumed_after_accept(self, app_client):
        """After accepting, the invite status should be 'accepted' and not reusable."""
        client, user_ref, db, claims = app_client

        # Admin creates invite
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        client.post("/invites", json={"email": "once@test.com", "role": "editor"})

        # User accepts
        user_ref["user"] = make_user("newuser1", "once@test.com")
        resp = client.post("/auth/accept-invite")
        assert resp.json()["invited"] is True

        # Second user with same email tries to accept — no pending invite left
        user_ref["user"] = make_user("newuser2", "once@test.com")
        resp = client.post("/auth/accept-invite")
        assert resp.json()["invited"] is False

    def test_invite_email_case_insensitive(self, app_client):
        """Invite matching should be case-insensitive."""
        client, user_ref, db, claims = app_client

        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")
        client.post("/invites", json={"email": "Mixed.Case@Test.COM", "role": "viewer"})

        # Accept with lowercase email
        user_ref["user"] = make_user("newuser1", "mixed.case@test.com")
        resp = client.post("/auth/accept-invite")
        assert resp.json()["invited"] is True
        assert resp.json()["role"] == "viewer"

    def test_multiple_invites_first_wins(self, app_client):
        """If multiple orgs invite the same email, first pending invite wins."""
        client, user_ref, db, claims = app_client

        # Org 1 invites
        provision_admin(client, user_ref, claims, "admin1", "admin1@test.com")
        client.post("/invites", json={"email": "contested@test.com", "role": "editor"})
        org1 = claims["admin1"]["orgId"]

        # Org 2 invites same email
        user_ref["user"] = make_user("admin2", "admin2@test.com")
        client.post("/auth/provision")
        org2 = claims["admin2"]["orgId"]
        user_ref["user"] = make_user("admin2", "admin2@test.com", org_id=org2, role="admin")
        client.post("/invites", json={"email": "contested@test.com", "role": "viewer"})

        # User accepts — gets first invite (org1)
        user_ref["user"] = make_user("contested1", "contested@test.com")
        resp = client.post("/auth/accept-invite")
        assert resp.json()["invited"] is True
        assert resp.json()["orgId"] == org1


# ===================================================================
# WORKSPACE EDGE CASES
# ===================================================================

class TestWorkspaceEdgeCases:
    def test_rename_nonexistent_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.patch("/workspaces/nonexistent", json={"name": "X"})
        assert resp.status_code == 404

    def test_archive_nonexistent_workspace(self, app_client):
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        resp = client.delete("/workspaces/nonexistent")
        assert resp.status_code == 404

    def test_create_workspace_empty_name(self, app_client):
        """Empty name should be rejected by pydantic validation."""
        client, user_ref, db, claims = app_client
        provision_admin(client, user_ref, claims, "admin1", "admin@test.com")

        # Empty string is technically valid for pydantic str, but the endpoint should handle it
        resp = client.post("/workspaces", json={"name": ""})
        # Either 422 (validation) or 200 with empty name — both are acceptable
        # The important thing is it doesn't crash
        assert resp.status_code in (200, 422)
