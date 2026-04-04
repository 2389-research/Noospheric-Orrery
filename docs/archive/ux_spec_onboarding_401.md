# Noospheric Orrery — Onboarding & Workspace UX Spec

*For the design agent. Covers naming, user flows, and every backend interface available.*

---

## Naming Convention

- **Noosphere** = a workspace. The container for a complete knowledge graph — documents, entities, domains, specs, pipeline jobs. Each noosphere is a separate knowledge universe.
- **Orrery** = the galaxy visualization. The interactive cosmic map showing entities as stars, domains as nebulae. The fun payoff tab. Currently called "Galaxy" — rename to "Orrery".
- **Org** = team/billing container. Holds members and noospheres. Most users will only have one. Keep it behind the scenes unless the user needs to manage team.

---

## Current State

### App Tabs (today)
```
Upload | Pipeline | Entities | Galaxy
```
- **Upload**: drag-and-drop document ingestion
- **Pipeline**: simmer jobs, extraction jobs, progress tracking
- **Entities**: browse/search/filter extracted entities
- **Galaxy**: cosmic Canvas2D visualization in an iframe

### What exists in the frontend
- Firebase Auth with Google sign-in (popup)
- `AuthProvider` context: `{ user, loading, session, workspaceId, setWorkspaceId, signIn, signOut }`
- `session` contains: `{ orgId, role, workspaces: [{id, name}] }`
- `AuthGate` component: shows landing page if not signed in, app if signed in
- `UserMenu` component: profile pic, name, sign-out button
- Every API call includes `Authorization: Bearer <token>` and `X-Workspace-Id: <id>` headers automatically
- No onboarding, no workspace switcher, no org management, no invite UI

### What exists in the backend
All endpoints require `Authorization: Bearer <firebase-id-token>` header.

---

## Backend API Reference

### Auth & Provisioning

#### `POST /auth/provision`
Called after sign-in. Idempotent — safe to call every time.
- **No body required**
- **Response** (new user):
```json
{
  "orgId": "DpJMHkuc6wO1nvwMesV0",
  "role": "admin",
  "workspaces": [{"id": "PkiZ8Qo2NSoXNERswTgX", "name": "Default"}]
}
```
- **Response** (returning user): same shape, returns existing org + workspaces
- **What it does**: Creates org (named `"{email prefix}'s Org"`), creates "Default" workspace, sets JWT claims `{orgId, role}`, writes token refresh sentinel

#### `POST /auth/accept-invite`
Called before provision for users who may have a pending invite.
- **No body required**
- **Response** (has invite):
```json
{"invited": true, "orgId": "abc123", "role": "editor"}
```
- **Response** (no invite):
```json
{"invited": false}
```
- **Response** (already provisioned):
```json
{"invited": false, "alreadyProvisioned": true}
```

### Invites (admin only)

#### `POST /invites`
```json
{"email": "alice@example.com", "role": "editor"}
```
Response: `{"inviteId": "...", "email": "...", "role": "..."}`

Role must be `"editor"` or `"viewer"`. Returns 400 for invalid roles. Returns 403 for non-admins.

#### `GET /invites`
Returns pending invites for the caller's org.
```json
[
  {
    "id": "LRS7TM3zBN5acixDeTQj",
    "email": "alice@example.com",
    "role": "editor",
    "orgId": "...",
    "createdBy": "...",
    "createdAt": "2026-04-01T05:23:16.424000+00:00",
    "status": "pending"
  }
]
```

#### `DELETE /invites/{invite_id}`
Revokes an invite. Returns `{"revoked": true}`. Returns 404 if invite belongs to different org.

### Workspaces (Noospheres)

#### `POST /workspaces` (admin only)
```json
{"name": "Research", "description": "Optional description"}
```
Response: `{"workspaceId": "hyYHE1e4VLRFfNGKRetw", "name": "Research"}`

#### `GET /workspaces` (viewer+)
Returns all active (non-archived) workspaces for the caller's org.
```json
[
  {
    "id": "PkiZ8Qo2NSoXNERswTgX",
    "name": "Default",
    "orgId": "DpJMHkuc6wO1nvwMesV0",
    "createdBy": "...",
    "createdAt": "...",
    "description": ""
  }
]
```

#### `PATCH /workspaces/{id}` (admin only)
```json
{"name": "New Name"}
```
Response: `{"updated": true}`

#### `DELETE /workspaces/{id}` (admin only)
Soft delete — sets `status: "archived"`. Response: `{"archived": true}`

### Existing Data Endpoints (all workspace-scoped via X-Workspace-Id header)

| Endpoint | What it returns |
|---|---|
| `GET /stats` | `{document_count, entity_count, domain_count, active_jobs}` |
| `GET /documents` | List of documents with title, status, domains |
| `GET /entities?limit=N&type=T` | List of entities with name, type, source_count |
| `GET /domains` | Domain taxonomy with doc counts |
| `GET /jobs` | Pipeline jobs with status, type, results |
| `GET /graph` | Full graph data for the orrery visualization |
| `POST /ingest` | Upload a document (multipart form) |
| `POST /simmer/general` | Trigger general spec simmering |
| `POST /normalize` | Trigger entity normalization |
| `GET /normalize/review` | Get entity pairs needing manual review |

### Role Hierarchy

| Role | Can do |
|---|---|
| **viewer** | Read all data, view orrery, browse entities |
| **editor** | Everything viewer + upload docs, trigger pipeline, resolve normalization reviews |
| **admin** | Everything editor + manage team, invites, create/archive noospheres |

Backend enforces this. Frontend should hide/disable UI elements accordingly.

### Token Refresh

When claims change (e.g., role update), the backend writes to `users/{uid}/tokenRefreshAt`. The frontend watches this Firestore doc and calls `getIdToken(true)` to force refresh. This is already wired up in `firebase.ts`.

---

## Brainstorming Notes

### Hierarchy
```
Org ("2389 Research")
├── Members: Michael (admin), Alice (editor), Bob (viewer)
├── Noosphere: "AI Research"
│   ├── documents, entities, domains, specs, jobs
│   └── Orrery = galaxy viz of THIS noosphere
├── Noosphere: "Client Project X"
│   └── totally separate knowledge graph
└── Noosphere: "Personal Notes"
    └── another separate graph
```

### Onboarding Flow Ideas

1. **Sign in** → call `POST /auth/accept-invite` then `POST /auth/provision`
2. **New user, no invite** → auto-create org + default noosphere. Maybe let them name it? Or just "My Noosphere" and rename later?
3. **New user, has invite** → "You've been invited to [Org Name]" — accept, land in that org's noosphere
4. **Returning user** → straight to last-used noosphere (store in localStorage?)
5. **Empty noosphere** → prominent "Upload your first document" CTA. Maybe a guided flow: upload → watch it classify → see entities appear → explore the orrery

### Noosphere Switcher Ideas

- Dropdown in nav bar: `"AI Research" ▾` → list of noospheres with counts
- Or a dedicated "home" page showing all noospheres as cards
- Creating a new noosphere from the switcher (admin only)
- URL: `/n/{noosphereId}/upload`, `/n/{noosphereId}/orrery`, etc.

### Nav Structure Idea
```
[Org Name]  Noosphere: "AI Research" ▾

  Upload | Pipeline | Entities | Orrery
```

### Key Decisions Needed
- Should org be visible/nameable during onboarding, or hidden and auto-named?
- What does "create a new noosphere" look like? Modal? Page? Just a name field?
- Should the noosphere switcher show stats (doc count, entity count)?
- Should creating noospheres be admin-only or editor-accessible?
- Does the empty orrery show a placeholder animation or just a message?
- Should there be an actual email sent for invites, or just "share a link / tell them to sign in"?

---

## Frontend Files to Know About

| File | What it does |
|---|---|
| `frontend/src/lib/firebase.ts` | Firebase init, `signInWithGoogle()`, `setupSession()`, `watchTokenRefresh()` |
| `frontend/src/lib/auth-context.tsx` | `AuthProvider` — holds `user`, `session`, `workspaceId`, `setWorkspaceId` |
| `frontend/src/lib/api.ts` | All API calls. `setApiWorkspaceId(id)` updates the `X-Workspace-Id` header globally |
| `frontend/src/lib/types.ts` | TypeScript types for all API responses |
| `frontend/src/app/layout.tsx` | Root layout — wraps app in `AuthProvider`, contains nav bar |
| `frontend/src/components/auth-gate.tsx` | Shows landing page if not signed in |
| `frontend/src/components/user-menu.tsx` | Profile pic + sign-out in nav |
| `frontend/src/app/page.tsx` | Upload page (`/`) |
| `frontend/src/app/pipeline/` | Pipeline page |
| `frontend/src/app/entities/` | Entities page |
| `frontend/src/app/viz/` | Galaxy/Orrery page |
| `frontend/public/cosmic-viz.html` | Self-contained Canvas2D orrery — DO NOT decompose |

### Design Constraints
- Dark/cosmic aesthetic — deep navy backgrounds, glowing elements, star-field textures
- Next.js App Router + Tailwind CSS
- Desktop-first, not a consumer app
- The orrery viz is an iframe — communicates via postMessage

---

## Deliverable Expected

A detailed UX spec covering:
1. User flow diagrams for onboarding (new user, invited user, returning user)
2. Noosphere switcher design (where it lives, what it shows, how to create new)
3. Org/team management page layout (invites, members, roles)
4. Empty state designs for each page
5. Role-based UI differences (what to hide/disable per role)
6. URL routing structure (`/n/{id}/...` or similar)
7. Component hierarchy (what React components are needed)
8. Nav bar redesign (incorporating noosphere switcher + org)
9. Edge cases and gotchas
