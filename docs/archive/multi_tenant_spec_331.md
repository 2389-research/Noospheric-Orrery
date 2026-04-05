# Orrery — Multi-Tenancy Migration Spec

*For the implementation agent. Covers every piece needed to go from
single shared workspace to full org/workspace/role isolation.*

---

## Schema Decision: Flat Workspaces with orgId

**Keep `workspaces/{workspaceId}/...` as the top-level path.**

Do NOT restructure to `organizations/{orgId}/workspaces/{workspaceId}/...`.

Rationale:
- Every collection path in `firestore_store.py` currently uses `workspaces/{id}/...`
- Nesting under orgs would require rewriting every query path — large blast radius
- Security isolation is achieved equally well via orgId field + security rules
- The functional outcome is identical at this scale
- Can restructure later if genuinely needed; it won't be

### What changes in the schema

Add two top-level collections alongside existing `workspaces/`:

```
organizations/                    ← NEW
  {orgId}/
    name: string
    createdAt: timestamp
    createdBy: uid

    members/                      ← NEW subcollection
      {userId}/
        role: "admin" | "editor" | "viewer"
        email: string
        joinedAt: timestamp

workspaces/                       ← EXISTS — minimal changes
  {workspaceId}/
    name: string
    orgId: string                 ← NEW FIELD (add to existing docs)
    createdBy: uid
    createdAt: timestamp
    description: string

    documents/, entities/, domains/, jobs/, specs/ ...  ← UNCHANGED

invites/                          ← NEW top-level collection
  {inviteId}/
    email: string                 (lowercase)
    role: string
    orgId: string
    workspaceId: string           (which workspace to give access to, optional)
    createdBy: uid
    createdAt: timestamp
    status: "pending" | "accepted" | "revoked"

users/                            ← NEW top-level collection (thin, for token refresh signal)
  {userId}/
    tokenRefreshAt: timestamp
    email: string
```

### Migration of existing workspace docs

The existing `default` workspace needs an `orgId` field added. During
provisioning of the first real user, assign them as owner of that workspace
by writing `orgId` onto it. One-time data migration, not a code migration.

---

## What Already Exists (don't rebuild)

- `AuthUser` dataclass with `uid`, `email`, `workspace_id`, `role`
- `get_current_user` and `require_role()` FastAPI dependencies
- All Firestore data already under `workspaces/{workspaceId}/...`
- Firebase Auth with Google sign-in
- JWT token validation middleware (`AUTH_REQUIRED=false` currently)
- `firestore_store.py` repository pattern — all queries go through this

---

## Custom Claims Structure

```python
# What gets embedded in every user's JWT
{
    "orgId": "org_abc123",
    "role": "editor"       # admin | editor | viewer
}
```

These are read by Firestore Security Rules via `request.auth.token.orgId`
and `request.auth.token.role`. No database read needed on every request.

**Claim size limit:** 1000 bytes per user. The above is ~40 bytes. Fine.

**Stale token problem:** After `set_custom_user_claims()`, the user's JWT
doesn't update until it naturally expires (~1 hour) OR the client forces a
refresh. Always write to `users/{uid}/tokenRefreshAt` after changing claims,
and have the frontend watch that doc and call `getIdToken(true)`.

---

## Part 1: Backend — Auth & Provisioning

### 1.1 Admin SDK helper

```python
# orchestrator/src/auth_admin.py
from firebase_admin import auth
import firebase_admin

# firebase_admin.initialize_app() should already be called at app startup
# Uses Application Default Credentials on Cloud Run automatically

def set_user_claims(uid: str, org_id: str, role: str) -> None:
    """Set org and role on a user's JWT. Call after any membership change."""
    auth.set_custom_user_claims(uid, {
        "orgId": org_id,
        "role": role,
    })

def get_user_claims(uid: str) -> dict:
    user = auth.get_user(uid)
    return user.custom_claims or {}

def signal_token_refresh(db, uid: str) -> None:
    """Write sentinel doc so frontend watcher forces getIdToken(true)."""
    from google.cloud import firestore
    db.collection("users").document(uid).set(
        {"tokenRefreshAt": firestore.SERVER_TIMESTAMP},
        merge=True,
    )
```

### 1.2 Provision endpoint

Called by the frontend immediately after first sign-in. Idempotent — safe to
call on every sign-in, it checks claims first.

```python
# orchestrator/src/routes/auth_routes.py
from fastapi import APIRouter, Depends
from google.cloud import firestore as fs
from src.auth import get_current_user, AuthUser
from src.auth_admin import set_user_claims, get_user_claims, signal_token_refresh

router = APIRouter()

@router.post("/auth/provision")
async def provision_user(
    user: AuthUser = Depends(get_current_user),
    db = Depends(get_db),
):
    """
    Creates org + default workspace on first sign-in.
    Returns existing org if already provisioned.
    Idempotent — safe to call on every sign-in.
    """
    claims = get_user_claims(user.uid)

    if claims.get("orgId"):
        # Already provisioned — find their workspaces and return
        workspaces = (
            db.collection("workspaces")
            .where("orgId", "==", claims["orgId"])
            .stream()
        )
        ws_list = [{"id": ws.id, **ws.to_dict()} for ws in workspaces]
        return {
            "orgId": claims["orgId"],
            "role": claims["role"],
            "workspaces": ws_list,
        }

    # New user — create org
    org_ref = db.collection("organizations").document()
    org_id = org_ref.id
    org_name = user.email.split("@")[0].replace(".", " ").title() + "'s Org"

    org_ref.set({
        "name": org_name,
        "createdAt": fs.SERVER_TIMESTAMP,
        "createdBy": user.uid,
    })

    # Add user as admin member
    org_ref.collection("members").document(user.uid).set({
        "role": "admin",
        "email": user.email,
        "joinedAt": fs.SERVER_TIMESTAMP,
    })

    # Create default workspace
    ws_ref = db.collection("workspaces").document()
    ws_ref.set({
        "name": "Default",
        "orgId": org_id,
        "createdBy": user.uid,
        "createdAt": fs.SERVER_TIMESTAMP,
        "description": "",
    })

    # Set claims
    set_user_claims(user.uid, org_id, "admin")
    signal_token_refresh(db, user.uid)

    return {
        "orgId": org_id,
        "role": "admin",
        "workspaces": [{"id": ws_ref.id, "name": "Default"}],
    }
```

### 1.3 Invite flow

```python
# orchestrator/src/routes/invite_routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from src.auth import get_current_user, require_role, AuthUser

router = APIRouter()

class InviteRequest(BaseModel):
    email: EmailStr
    role: str  # "editor" | "viewer"

@router.post("/invites")
async def create_invite(
    req: InviteRequest,
    user: AuthUser = Depends(require_role("admin")),
    db = Depends(get_db),
):
    """Admin creates an invite. Invitee accepts on next sign-in."""
    if req.role not in ("editor", "viewer"):
        raise HTTPException(400, "role must be editor or viewer")

    invite_ref = db.collection("invites").document()
    invite_ref.set({
        "email": req.email.lower(),
        "role": req.role,
        "orgId": user.org_id,
        "createdBy": user.uid,
        "createdAt": fs.SERVER_TIMESTAMP,
        "status": "pending",
    })
    return {"inviteId": invite_ref.id, "email": req.email, "role": req.role}


@router.get("/invites")
async def list_invites(
    user: AuthUser = Depends(require_role("admin")),
    db = Depends(get_db),
):
    """List pending invites for this org."""
    invites = (
        db.collection("invites")
        .where("orgId", "==", user.org_id)
        .where("status", "==", "pending")
        .stream()
    )
    return [{"id": inv.id, **inv.to_dict()} for inv in invites]


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: str,
    user: AuthUser = Depends(require_role("admin")),
    db = Depends(get_db),
):
    invite_ref = db.collection("invites").document(invite_id)
    invite = invite_ref.get().to_dict()
    if not invite or invite.get("orgId") != user.org_id:
        raise HTTPException(404, "Invite not found")
    invite_ref.update({"status": "revoked"})
    return {"revoked": True}


@router.post("/auth/accept-invite")
async def accept_invite(
    user: AuthUser = Depends(get_current_user),
    db = Depends(get_db),
):
    """
    Called after sign-in when user has no claims (new user with an invite).
    Checks for pending invite matching their email.
    """
    claims = get_user_claims(user.uid)
    if claims.get("orgId"):
        return {"invited": False, "alreadyProvisioned": True}

    invites = (
        db.collection("invites")
        .where("email", "==", user.email.lower())
        .where("status", "==", "pending")
        .limit(1)
        .stream()
    )
    invite_list = list(invites)

    if not invite_list:
        return {"invited": False}

    invite_doc = invite_list[0]
    invite = invite_doc.to_dict()
    org_id = invite["orgId"]
    role = invite["role"]

    # Add member to org
    db.collection("organizations").document(org_id)\
      .collection("members").document(user.uid).set({
        "role": role,
        "email": user.email,
        "joinedAt": fs.SERVER_TIMESTAMP,
    })

    # Set claims
    set_user_claims(user.uid, org_id, role)
    signal_token_refresh(db, user.uid)

    # Mark invite consumed
    invite_doc.reference.update({"status": "accepted"})

    return {"invited": True, "orgId": org_id, "role": role}
```

### 1.4 Workspace CRUD

```python
# orchestrator/src/routes/workspace_routes.py

@router.post("/workspaces")
async def create_workspace(
    name: str,
    description: str = "",
    user: AuthUser = Depends(require_role("admin")),
    db = Depends(get_db),
):
    ws_ref = db.collection("workspaces").document()
    ws_ref.set({
        "name": name,
        "description": description,
        "orgId": user.org_id,
        "createdBy": user.uid,
        "createdAt": fs.SERVER_TIMESTAMP,
    })
    return {"workspaceId": ws_ref.id, "name": name}


@router.get("/workspaces")
async def list_workspaces(
    user: AuthUser = Depends(require_role("viewer")),
    db = Depends(get_db),
):
    """Return all workspaces the user's org can access."""
    workspaces = (
        db.collection("workspaces")
        .where("orgId", "==", user.org_id)
        .stream()
    )
    return [{"id": ws.id, **ws.to_dict()} for ws in workspaces]


@router.patch("/workspaces/{workspace_id}")
async def rename_workspace(
    workspace_id: str,
    name: str,
    user: AuthUser = Depends(require_role("admin")),
    db = Depends(get_db),
):
    ws_ref = db.collection("workspaces").document(workspace_id)
    ws = ws_ref.get().to_dict()
    if not ws or ws.get("orgId") != user.org_id:
        raise HTTPException(404)
    ws_ref.update({"name": name})
    return {"updated": True}


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    user: AuthUser = Depends(require_role("admin")),
    db = Depends(get_db),
):
    """
    Soft delete or full delete — recommend soft delete (set status: "archived")
    rather than actually deleting Firestore subcollections, which requires
    recursive batch deletes and is irreversible.
    """
    ws_ref = db.collection("workspaces").document(workspace_id)
    ws = ws_ref.get().to_dict()
    if not ws or ws.get("orgId") != user.org_id:
        raise HTTPException(404)
    ws_ref.update({"status": "archived", "archivedAt": fs.SERVER_TIMESTAMP})
    return {"archived": True}
```

### 1.5 Update AuthUser to include org_id

The existing `AuthUser` dataclass needs `org_id` populated from the JWT claim.
Update `get_current_user` in `auth.py`:

```python
# In get_current_user dependency — read orgId from decoded token claims
auth_user = AuthUser(
    uid=decoded_token["uid"],
    email=decoded_token.get("email", ""),
    workspace_id=decoded_token.get("workspaceId") or DEFAULT_WORKSPACE_ID,
    role=decoded_token.get("role", "viewer"),
    org_id=decoded_token.get("orgId", ""),   # ← add this field to AuthUser
)
```

The `workspace_id` on `AuthUser` now comes from the request header or query
param (user selects which workspace they're working in), not the JWT. The JWT
carries `orgId` and `role` — which workspace they're operating on is a
session-level choice they pass to each request.

**Recommended:** Accept `X-Workspace-Id` header on API requests. Validate that
the requested workspace's `orgId` matches the user's `orgId` claim before
serving any data.

```python
# In get_current_user or a separate workspace validation dependency:
async def get_workspace(
    x_workspace_id: str = Header(...),
    user: AuthUser = Depends(get_current_user),
    db = Depends(get_db),
) -> str:
    ws = db.collection("workspaces").document(x_workspace_id).get().to_dict()
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if ws.get("orgId") != user.org_id:
        raise HTTPException(403, "Workspace does not belong to your org")
    return x_workspace_id
```

---

## Part 2: Firestore Security Rules

These rules are the safety net for direct client SDK access. All backend
services use the Admin SDK and bypass these — that is correct and expected.

```javascript
// firestore.rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // ── Helper functions ──────────────────────────────────────────────────

    function signedIn() {
      return request.auth != null;
    }

    function userOrg() {
      return request.auth.token.get('orgId', null);
    }

    function userRole() {
      return request.auth.token.get('role', 'viewer');
    }

    function isAdmin() {
      return signedIn() && userRole() == 'admin';
    }

    function isEditor() {
      return signedIn() && userRole() in ['admin', 'editor'];
    }

    function isViewer() {
      return signedIn() && userRole() in ['admin', 'editor', 'viewer'];
    }

    function ownsOrg(orgId) {
      return signedIn() && userOrg() == orgId;
    }

    function ownsWorkspace(workspaceId) {
      // Reads the workspace doc to verify orgId — costs 1 read op
      // Only use this where necessary; prefer org-scoped paths
      return signedIn() &&
        get(/databases/$(database)/documents/workspaces/$(workspaceId)).data.orgId == userOrg();
    }

    // ── Organizations ─────────────────────────────────────────────────────

    match /organizations/{orgId} {
      allow read: if ownsOrg(orgId) && isViewer();
      allow write: if ownsOrg(orgId) && isAdmin();

      match /members/{userId} {
        allow read: if ownsOrg(orgId) && isViewer();
        // Only admins can add/change members
        // Members cannot change their own role
        allow write: if ownsOrg(orgId) && isAdmin();
      }
    }

    // ── Workspaces ────────────────────────────────────────────────────────

    match /workspaces/{workspaceId} {
      // Allow read if workspace's orgId matches user's org
      allow read: if signedIn() &&
        resource.data.orgId == userOrg() &&
        isViewer();

      allow create: if signedIn() &&
        request.resource.data.orgId == userOrg() &&
        isEditor();

      allow update: if signedIn() &&
        resource.data.orgId == userOrg() &&
        isAdmin();

      allow delete: if false; // Use soft delete (archived field) only

      // ── Workspace subcollections ───────────────────────────────────────
      // All data lives here. Same pattern: org match + role check.

      match /documents/{docId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow create, update: if ownsWorkspace(workspaceId) && isEditor();
        allow delete: if false;

        match /chunks/{chunkId} {
          allow read: if ownsWorkspace(workspaceId) && isViewer();
          allow write: if ownsWorkspace(workspaceId) && isEditor();
        }

        match /domains/{domainPath} {
          allow read: if ownsWorkspace(workspaceId) && isViewer();
          allow write: if ownsWorkspace(workspaceId) && isEditor();
        }
      }

      match /entities/{entityId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow create, update: if ownsWorkspace(workspaceId) && isEditor();
        allow delete: if false;

        match /sources/{sourceId} {
          allow read: if ownsWorkspace(workspaceId) && isViewer();
          allow write: if ownsWorkspace(workspaceId) && isEditor();
        }
      }

      match /domains/{domainId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow write: if ownsWorkspace(workspaceId) && isEditor();
      }

      match /jobs/{jobId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow create: if ownsWorkspace(workspaceId) && isEditor();
        allow update: if false; // Only backend updates job status
        allow delete: if false;

        match /iterations/{iterationId} {
          allow read: if ownsWorkspace(workspaceId) && isViewer();
          allow write: if false; // Backend only
        }
      }

      match /specs/{specId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow write: if false; // Backend only
      }

      match /relationships/{relId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow write: if false; // Backend only
      }

      match /normalizationQueue/{reviewId} {
        allow read: if ownsWorkspace(workspaceId) && isViewer();
        allow update: if ownsWorkspace(workspaceId) && isEditor();
        allow create, delete: if false;
      }
    }

    // ── Invites ───────────────────────────────────────────────────────────
    // Invites are readable by the invitee (matched by email via backend)
    // and by org admins. Write is backend-only.

    match /invites/{inviteId} {
      allow read: if signedIn() && (
        resource.data.orgId == userOrg() ||
        resource.data.email == request.auth.token.email
      );
      allow write: if false; // Backend only
    }

    // ── User sentinel docs (token refresh signal) ─────────────────────────

    match /users/{userId} {
      allow read: if request.auth.uid == userId;
      allow write: if false; // Backend only via Admin SDK
    }
  }
}
```

> **Test rules before deploying.** Use Firebase Console → Firestore → Rules →
> Rules Playground. Simulate reads/writes as different users with different
> claims before going live. A misconfigured rule that's too permissive is a
> security hole; one that's too restrictive breaks the app silently.

---

## Part 3: Frontend

### 3.1 Sign-in and provision flow

```javascript
// frontend/src/lib/auth.js

import { getAuth, signInWithPopup, GoogleAuthProvider, onAuthStateChanged } from 'firebase/auth';
import { doc, onSnapshot } from 'firebase/firestore';

const auth = getAuth();
const provider = new GoogleAuthProvider();

export async function signIn() {
  const result = await signInWithPopup(auth, provider);
  return result.user;
}

// Call this once after sign-in to set up the session
export async function setupSession(user, db, apiClient) {
  // 1. Check for pending invite first
  const inviteResult = await apiClient.post('/auth/accept-invite');

  // 2. Provision (creates org if new user, returns existing org if returning)
  const session = await apiClient.post('/auth/provision');

  // 3. Watch for token refresh signal
  watchTokenRefresh(user.uid, db, auth);

  return session; // { orgId, role, workspaces: [...] }
}

export function watchTokenRefresh(userId, db, auth) {
  const userDocRef = doc(db, 'users', userId);
  return onSnapshot(userDocRef, async (snap) => {
    if (snap.exists()) {
      await auth.currentUser?.getIdToken(true);
      console.log('[auth] Token refreshed after claims update');
      // Optionally: trigger a re-fetch of user session data here
    }
  });
}
```

### 3.2 Workspace selector component

```jsx
// frontend/src/components/WorkspaceSelector.jsx
import { useState, useEffect } from 'react';
import { collection, query, where, onSnapshot } from 'firebase/firestore';
import { useNavigate, useParams } from 'react-router-dom';

export function WorkspaceSelector({ orgId, db }) {
  const [workspaces, setWorkspaces] = useState([]);
  const { workspaceId } = useParams();
  const navigate = useNavigate();

  useEffect(() => {
    if (!orgId) return;
    const q = query(
      collection(db, 'workspaces'),
      where('orgId', '==', orgId),
    );
    return onSnapshot(q, (snap) => {
      setWorkspaces(
        snap.docs
          .map(d => ({ id: d.id, ...d.data() }))
          .filter(ws => ws.status !== 'archived')
      );
    });
  }, [orgId]);

  function handleSwitch(newWorkspaceId) {
    // Preserve the current route, swap workspace segment
    const currentPath = window.location.pathname;
    const newPath = currentPath.replace(
      `/w/${workspaceId}`,
      `/w/${newWorkspaceId}`
    );
    navigate(newPath);
  }

  return (
    <select value={workspaceId} onChange={e => handleSwitch(e.target.value)}>
      {workspaces.map(ws => (
        <option key={ws.id} value={ws.id}>{ws.name}</option>
      ))}
    </select>
  );
}
```

### 3.3 URL routing

All workspace-scoped routes get a `/w/:workspaceId` prefix. The selected
workspace ID is passed as the `X-Workspace-Id` header on every API call.

```
/w/:workspaceId/viz          ← galaxy
/w/:workspaceId/entities     ← entity explorer
/w/:workspaceId/upload       ← ingest
/w/:workspaceId/pipeline     ← job dashboard
/w/:workspaceId/settings     ← workspace settings (admin only)

/settings/team               ← org-level: invite management
/settings/workspaces         ← org-level: workspace CRUD
```

```javascript
// Axios / fetch interceptor — attach workspace ID to every API call
apiClient.interceptors.request.use(async (config) => {
  const user = auth.currentUser;
  if (user) {
    const token = await user.getIdToken();
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  // Read current workspaceId from URL
  const match = window.location.pathname.match(/\/w\/([^\/]+)/);
  if (match) {
    config.headers['X-Workspace-Id'] = match[1];
  }
  return config;
});
```

---

## Part 4: Enable AUTH_REQUIRED

Once the above is deployed and tested, flip the orchestrator:

```bash
gcloud run services update orrery-orchestrator \
  --region=us-central1 \
  --update-env-vars AUTH_REQUIRED=true
```

Do this last. Test with it off first so auth bugs don't block functional
testing of everything else.

---

## Implementation Order

Do these in sequence. Each step is independently testable.

### Step 1 — Claims + provision (1 day)
1. Add `org_id` field to `AuthUser` dataclass
2. Update `get_current_user` to read `orgId` from JWT claims
3. Write `auth_admin.py` helper (set_user_claims, get_user_claims, signal_token_refresh)
4. Implement `POST /auth/provision` endpoint
5. Test: sign in, call provision, verify org + workspace created in Firestore,
   verify custom claims set on user (check with `auth.get_user(uid).custom_claims`)

### Step 2 — Invite flow (1 day)
1. Implement `POST /invites`, `GET /invites`, `DELETE /invites/{id}`
2. Implement `POST /auth/accept-invite`
3. Test: create invite for a second test account, sign in with that account,
   verify claims set and member doc created

### Step 3 — Workspace validation (0.5 days)
1. Implement `get_workspace` dependency that validates `X-Workspace-Id` header
2. Wire it into existing routes (ingest, graph, search, entities)
3. Test: request with workspace belonging to a different org returns 403

### Step 4 — Workspace CRUD (0.5 days)
1. Implement workspace create, list, rename, archive endpoints
2. Test: create second workspace, confirm it appears in list

### Step 5 — Security rules (0.5 days)
1. Write rules per Part 2
2. Test every rule path in Firebase Rules Playground before deploying
3. Deploy rules
4. Test: confirm frontend gets permission denied if it tries to read another
   org's workspace directly (bypassing the backend)

### Step 6 — Frontend (2 days)
1. Implement `setupSession()` — calls provision + accept-invite on sign-in
2. Implement token refresh watcher
3. Add workspace selector component to nav
4. Implement `/w/:workspaceId/...` URL routing
5. Add `X-Workspace-Id` header interceptor on API client
6. Test: switch workspaces, confirm data changes

### Step 7 — Enable AUTH_REQUIRED (0.5 days)
1. Update Cloud Run env var
2. Full end-to-end test as two separate users in two separate orgs
3. Verify cross-org isolation

---

## Gotchas

**ownsWorkspace() in security rules costs a read.** The `get()` call inside
`ownsWorkspace()` is billed as a Firestore read operation per rule evaluation.
For a low-traffic internal tool this is fine. If it becomes a cost concern,
denormalize `orgId` onto every subcollection document and check
`resource.data.orgId == userOrg()` directly instead.

**Composite index for workspace queries.** The query
`where("orgId", "==", ...).where("status", "!=", "archived")` needs a
composite index. Run it once, Firestore will error with the exact gcloud
command to create it.

**Don't delete Firestore subcollections.** Deleting a workspace doc does not
delete its subcollections — Firestore has no cascade delete. Use soft delete
(archived status) and exclude archived workspaces from queries. If you genuinely
need to purge data, use the Firebase Admin SDK's recursive delete helper:
`firebase_admin.firestore.async_delete_collection()`.

**Role changes take effect on next token refresh.** If you downgrade someone
from editor to viewer, they retain editor-level access until their token
refreshes. The `signal_token_refresh()` + frontend watcher pattern handles
this, but there's still a small window (~seconds) between the backend write
and the frontend receiving the snapshot. For security-critical role changes,
revoke the refresh token entirely via `auth.revoke_refresh_tokens(uid)`.

**Invites don't expire.** Add a `expiresAt` field and check it in
`accept-invite` if you want time-limited invites. Not required for v1.

**The default workspace needs orgId.** The existing `default` workspace in
Firestore has no `orgId` field. When the first real user provisions, write
`orgId` onto that workspace doc as part of the provision flow, or run a
one-time migration script.
