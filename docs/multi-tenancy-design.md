# Multi-Tenancy — Org / Workspace / Team Design

## Current State (as of firebase-migration branch)
- Single shared `default` workspace
- All users see the same data
- Auth via Firebase Google sign-in (JWT tokens)
- Workspace ID comes from env var or auth token claims

## Planned Architecture

### Hierarchy
```
Organization (team/company)
  └── Workspace (knowledge graph segment)
       └── Data (documents, entities, domains, specs, etc.)
```

### Organization
- Created by first user who signs up with a given email domain (e.g., @2389.ai)
- Or created manually by admin
- Has members with roles: admin, editor, viewer
- Owns one or more workspaces

### Workspace
- A named knowledge graph: "2389 Meeting Notes", "Warhammer Research", "Legal Docs"
- Each has its own: domain taxonomy, extraction specs, entities, UMAP layout
- Data is fully isolated between workspaces
- A user can access multiple workspaces within their org

### Roles
| Role | Can do |
|------|--------|
| Admin | Manage members, create/delete workspaces, all editor actions |
| Editor | Upload docs, trigger simmers, resolve normalizations, search |
| Viewer | Browse entities, search, use galaxy viz (read-only) |

### Auth Flow
1. User signs in with Google (Firebase Auth)
2. Backend checks custom claims on their JWT: `{ orgId, role, workspaceId }`
3. Store is scoped to their workspace: `workspaces/{workspaceId}/...`
4. Custom claims set by admin via server-side Firebase Admin SDK

### Firestore Structure
```
organizations/
  {orgId}/
    name, createdAt
    members/
      {userId}/
        role, email, joinedAt

workspaces/
  {workspaceId}/
    name, orgId, createdBy, createdAt
    documents/...
    entities/...
    domains/...
    (all data collections)
```

### Invite Flow
1. Admin enters email on team settings page
2. Backend creates a pending invite doc
3. Invitee signs in → backend checks for pending invites matching their email
4. If found, set custom claims with orgId + role → invitee sees the org's workspaces

### Workspace Selector
- Dropdown in nav bar showing user's accessible workspaces
- Switching workspace reloads the data layer (new store with different workspaceId)
- URL includes workspace: `/w/{workspaceId}/viz`, `/w/{workspaceId}/entities`

### Sharing with External Users (Investors)
- Admin creates a viewer-only invite
- Investor signs in with Google → gets viewer role
- Can browse the galaxy, search, see entities — but can't upload or modify
- Could also support time-limited share links (future)

## Implementation Order
1. Org creation + admin role on first sign-in
2. Invite flow (admin → pending invite → invitee claims)
3. Workspace CRUD (create, rename, delete)
4. Workspace selector in UI
5. Role enforcement on API endpoints
6. Viewer share links for investors

## What Exists Already
- `AuthUser` dataclass with uid, email, workspace_id, role
- `get_auth_store` dependency scopes store to user's workspace
- `require_role()` dependency for RBAC checks
- Firebase custom claims support in auth.py
- All routes accept auth dependency
- Firestore collections namespaced under `workspaces/{id}/`
