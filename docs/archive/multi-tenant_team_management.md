# Orrery — Noosphere & Team Management Pages Spec

*For the implementation agent. Covers URL routing restructure, noosphere
switcher, workspace management page, and team management page. This is
the prerequisite infrastructure before the onboarding tutorial can be built.*

---

## What Already Exists (do not rebuild)

From `frontend/src/`:

```
lib/firebase.ts          — Firebase init, signInWithGoogle(), setupSession(), watchTokenRefresh()
lib/auth-context.tsx     — AuthProvider: { user, loading, session, workspaceId, setWorkspaceId, signIn, signOut }
                           session = { orgId, role, workspaces: [{id, name}] }
lib/api.ts               — All API calls. setApiWorkspaceId(id) sets X-Workspace-Id globally
lib/types.ts             — TypeScript types for API responses
app/layout.tsx           — Root layout, wraps in AuthProvider, contains nav bar
components/auth-gate.tsx — Shows landing if not signed in
components/user-menu.tsx — Profile pic + sign-out
app/page.tsx             — Upload page (/)
app/pipeline/            — Pipeline page
app/entities/            — Entities page
app/viz/                 — Galaxy/Orrery page
public/cosmic-viz.html   — Canvas2D orrery iframe — DO NOT TOUCH
```

Backend endpoints already built and tested:
- `POST /auth/provision` — creates/returns org + workspaces
- `POST /auth/accept-invite` — claims pending invite
- `POST /invites`, `GET /invites`, `DELETE /invites/{id}`
- `POST /workspaces`, `GET /workspaces`, `PATCH /workspaces/{id}`, `DELETE /workspaces/{id}`
- All data endpoints scoped via `X-Workspace-Id` header

---

## Phase 1: URL Routing Restructure

### The Problem

Currently all pages live at `/`, `/pipeline`, `/entities`, `/viz`. There's no
workspace ID in the URL. Switching workspace requires state mutation with no
URL to bookmark, share, or reload. The noosphere switcher needs workspace ID
in the URL to function correctly.

### Target URL Structure

```
/                              → redirect to /n/{lastWorkspaceId}/upload (or /n/{defaultId}/upload)
/n/[noosphereId]/upload        → Upload page
/n/[noosphereId]/pipeline      → Pipeline page
/n/[noosphereId]/entities      → Entities page
/n/[noosphereId]/orrery        → Orrery page (renamed from /viz)
/settings/team                 → Team management (org-level)
/settings/noospheres           → Noosphere list + management
```

### File Structure Changes

```
frontend/src/app/
  page.tsx                           ← CHANGE: redirect logic only
  n/
    [noosphereId]/
      layout.tsx                     ← NEW: workspace layout wrapper
      upload/
        page.tsx                     ← MOVE from app/page.tsx
      pipeline/
        page.tsx                     ← MOVE from app/pipeline/page.tsx
      entities/
        page.tsx                     ← MOVE from app/entities/page.tsx
      orrery/
        page.tsx                     ← MOVE from app/viz/page.tsx (rename)
  settings/
    layout.tsx                       ← NEW: settings layout (shared nav)
    team/
      page.tsx                       ← NEW
    noospheres/
      page.tsx                       ← NEW
```

### Root Redirect (`app/page.tsx`)

The root page now only handles redirect logic. It's a client component because
it needs auth context.

```tsx
// app/page.tsx
'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'

export default function RootPage() {
  const { session, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (loading) return

    // Read last used workspace from localStorage
    const lastId = localStorage.getItem('lastWorkspaceId')

    if (session?.workspaces?.length) {
      // Use lastId if it's in the user's workspace list, else use first workspace
      const valid = session.workspaces.find(w => w.id === lastId)
      const target = valid ? lastId : session.workspaces[0].id
      router.replace(`/n/${target}/upload`)
    }
    // If no session, AuthGate handles the sign-in redirect
  }, [session, loading, router])

  return null // AuthGate in layout handles the loading/sign-in state
}
```

### Workspace Layout (`app/n/[noosphereId]/layout.tsx`)

This layout wraps all workspace pages. It syncs the URL param into auth
context and the API client, validates the workspace belongs to the user,
and renders the nav with the noosphere switcher.

```tsx
// app/n/[noosphereId]/layout.tsx
'use client'
import { useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { setApiWorkspaceId } from '@/lib/api'
import { NavBar } from '@/components/nav-bar'

export default function NoosphereLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { noosphereId } = useParams<{ noosphereId: string }>()
  const { session, setWorkspaceId } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!noosphereId || !session) return

    // Validate this workspace belongs to the user's org
    const isValid = session.workspaces.some(w => w.id === noosphereId)
      || noosphereId === process.env.NEXT_PUBLIC_MAGOS_WORKSPACE_ID

    if (!isValid) {
      // Workspace doesn't belong to this user — redirect to their first workspace
      const fallback = session.workspaces[0]?.id
      if (fallback) router.replace(`/n/${fallback}/upload`)
      return
    }

    // Sync URL → context and API client
    setWorkspaceId(noosphereId)
    setApiWorkspaceId(noosphereId)
    localStorage.setItem('lastWorkspaceId', noosphereId)
  }, [noosphereId, session])

  return (
    <div className="flex flex-col h-screen">
      <NavBar currentNoosphereId={noosphereId} />
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  )
}
```

**Key point:** `setWorkspaceId` and `setApiWorkspaceId` are called from the
layout — not from individual pages. Every page under `/n/[noosphereId]/`
automatically gets the correct workspace context.

### Switching Workspaces

When the user picks a different workspace from the switcher, navigate to the
same tab in the new workspace:

```typescript
// lib/navigation.ts
export function switchNoosphere(
  currentPath: string,
  currentId: string,
  newId: string,
  router: ReturnType<typeof useRouter>
) {
  // Replace the current noosphereId segment in the path
  const newPath = currentPath.replace(`/n/${currentId}`, `/n/${newId}`)
  router.push(newPath)
}
```

---

## Phase 2: NavBar Redesign

The nav bar gains the noosphere switcher and renames "Galaxy" to "Orrery".

### New NavBar Layout

```
[Logo]  [✦ Michael's Noosphere ▾]   Upload | Pipeline | Entities | Orrery   [UserMenu ▾]
```

### NavBar Component

```tsx
// components/nav-bar.tsx
'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { NoosphereSwitcher } from './noosphere-switcher'
import { UserMenu } from './user-menu'

const TABS = [
  { label: 'Upload',   href: 'upload'   },
  { label: 'Pipeline', href: 'pipeline' },
  { label: 'Entities', href: 'entities' },
  { label: 'Orrery',   href: 'orrery'   },
]

export function NavBar({ currentNoosphereId }: { currentNoosphereId: string }) {
  const pathname = usePathname()

  function isActive(tab: string) {
    return pathname.includes(`/${tab}`)
  }

  return (
    <nav className="flex items-center gap-6 px-6 h-12 border-b border-white/10 bg-[#01040a]">
      {/* Logo */}
      <span className="text-teal-400 font-mono text-sm tracking-widest">ORRERY</span>

      {/* Noosphere Switcher */}
      <NoosphereSwitcher currentId={currentNoosphereId} />

      {/* Spacer */}
      <div className="flex-1" />

      {/* Tab navigation */}
      <div className="flex items-center gap-1">
        {TABS.map(tab => (
          <Link
            key={tab.href}
            href={`/n/${currentNoosphereId}/${tab.href}`}
            className={`px-3 py-1 text-xs font-mono tracking-wider rounded transition-colors ${
              isActive(tab.href)
                ? 'text-teal-400 bg-teal-400/10'
                : 'text-white/40 hover:text-white/70'
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </div>

      {/* User menu */}
      <UserMenu />
    </nav>
  )
}
```

---

## Phase 3: Noosphere Switcher Component

The dropdown that lists all workspaces, handles switching, and lets admins
create new ones.

### Data Flow

The switcher reads workspaces from two sources:
1. `session.workspaces` from auth context (fast, available immediately)
2. A Firestore `onSnapshot` listener on `workspaces` where `orgId == userOrgId`
   (live updates — new workspaces appear instantly without refresh)

Use `session.workspaces` for the initial render, then upgrade to the live
Firestore listener.

### Custom Hook: `useWorkspaces`

```typescript
// lib/hooks/use-workspaces.ts
'use client'
import { useState, useEffect } from 'react'
import { collection, query, where, onSnapshot } from 'firebase/firestore'
import { db } from '@/lib/firebase'
import { useAuth } from '@/lib/auth-context'

export interface Workspace {
  id: string
  name: string
  orgId: string
  description?: string
  status?: string
  isDemo?: boolean
}

export function useWorkspaces() {
  const { session } = useAuth()
  const [workspaces, setWorkspaces] = useState<Workspace[]>(
    session?.workspaces ?? []   // hydrate from session immediately
  )
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!session?.orgId) return

    const q = query(
      collection(db, 'workspaces'),
      where('orgId', '==', session.orgId),
    )

    const unsubscribe = onSnapshot(q, (snapshot) => {
      const ws = snapshot.docs
        .map(doc => ({ id: doc.id, ...doc.data() } as Workspace))
        .filter(ws => ws.status !== 'archived')  // exclude archived

      setWorkspaces(ws)
      setLoading(false)
    })

    return () => unsubscribe()
  }, [session?.orgId])

  return { workspaces, loading }
}
```

### Switcher Component

```tsx
// components/noosphere-switcher.tsx
'use client'
import { useState, useRef, useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useWorkspaces } from '@/lib/hooks/use-workspaces'
import { CreateNoosphereModal } from './create-noosphere-modal'
import { switchNoosphere } from '@/lib/navigation'

const MAGOS_ID = process.env.NEXT_PUBLIC_MAGOS_WORKSPACE_ID

export function NoosphereSwitcher({ currentId }: { currentId: string }) {
  const [open, setOpen] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const { session } = useAuth()
  const { workspaces } = useWorkspaces()
  const router = useRouter()
  const pathname = usePathname()
  const dropdownRef = useRef<HTMLDivElement>(null)

  const currentName = workspaces.find(w => w.id === currentId)?.name
    ?? (currentId === MAGOS_ID ? "Magos Noo's Noosphere" : 'Noosphere')

  const isAdmin = session?.role === 'admin'

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function handleSwitch(id: string) {
    setOpen(false)
    if (id === currentId) return
    switchNoosphere(pathname, currentId, id, router)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1 rounded border border-white/10
                   text-white/70 hover:text-white hover:border-white/20 text-xs font-mono
                   transition-colors"
      >
        <span className="max-w-[180px] truncate">{currentName}</span>
        <span className="text-white/30">▾</span>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full left-0 mt-1 w-64 rounded border border-white/10
                        bg-[#080d14] shadow-xl z-50 py-1">

          {/* Magos Noosphere — always first */}
          {MAGOS_ID && (
            <>
              <button
                onClick={() => handleSwitch(MAGOS_ID)}
                className="w-full flex items-center justify-between px-3 py-2
                           text-xs font-mono text-amber-400/70 hover:bg-white/5 transition-colors"
              >
                <span className="flex items-center gap-2">
                  <span>✦</span>
                  <span>Magos Noo's Noosphere</span>
                </span>
                <span className="text-white/20 text-[10px]">demo</span>
              </button>
              <div className="border-t border-white/10 my-1" />
            </>
          )}

          {/* User's workspaces */}
          {workspaces.map(ws => (
            <button
              key={ws.id}
              onClick={() => handleSwitch(ws.id)}
              className="w-full flex items-center justify-between px-3 py-2
                         text-xs font-mono text-white/60 hover:bg-white/5
                         hover:text-white transition-colors"
            >
              <span className="truncate">{ws.name}</span>
              {ws.id === currentId && (
                <span className="text-teal-400 text-[10px]">✓</span>
              )}
            </button>
          ))}

          {/* Divider + Create (admin only) */}
          {isAdmin && (
            <>
              <div className="border-t border-white/10 my-1" />
              <button
                onClick={() => { setOpen(false); setShowCreate(true) }}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs font-mono
                           text-teal-400/60 hover:text-teal-400 hover:bg-teal-400/5 transition-colors"
              >
                <span>+</span>
                <span>New Noosphere</span>
              </button>
            </>
          )}
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateNoosphereModal
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            setShowCreate(false)
            switchNoosphere(pathname, currentId, id, router)
          }}
        />
      )}
    </div>
  )
}
```

### Create Noosphere Modal

```tsx
// components/create-noosphere-modal.tsx
'use client'
import { useState } from 'react'
import { createWorkspace } from '@/lib/api'

export function CreateNoosphereModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleCreate() {
    if (!name.trim()) { setError('Name required'); return }
    setLoading(true)
    try {
      const { workspaceId } = await createWorkspace(name.trim(), description.trim())
      onCreated(workspaceId)
    } catch (e) {
      setError('Failed to create noosphere')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-[#080d14] border border-white/10 rounded-lg p-6 w-96">
        <h2 className="text-white font-mono text-sm mb-4">Create a Noosphere</h2>

        <label className="block text-white/40 text-xs font-mono mb-1">Name</label>
        <input
          autoFocus
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleCreate()}
          placeholder="Research Notes"
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2
                     text-white text-sm font-mono mb-3 focus:outline-none
                     focus:border-teal-400/50"
        />

        <label className="block text-white/40 text-xs font-mono mb-1">
          Description <span className="text-white/20">(optional)</span>
        </label>
        <input
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="What will you map?"
          className="w-full bg-white/5 border border-white/10 rounded px-3 py-2
                     text-white text-sm font-mono mb-4 focus:outline-none
                     focus:border-teal-400/50"
        />

        {error && <p className="text-red-400 text-xs font-mono mb-3">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-mono text-white/40 hover:text-white/70"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={loading}
            className="px-4 py-2 text-xs font-mono bg-teal-400/10 border border-teal-400/30
                       text-teal-400 rounded hover:bg-teal-400/20 disabled:opacity-40"
          >
            {loading ? 'Creating...' : 'Create Noosphere'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

---

## Phase 4: UserMenu Update

Add "Team Settings" and "Noospheres" links for admins. Link to settings pages.

```tsx
// components/user-menu.tsx (additions only)
import { useAuth } from '@/lib/auth-context'
import Link from 'next/link'

// Inside the dropdown menu:
const { session } = useAuth()
const isAdmin = session?.role === 'admin'

// Add to existing dropdown:
{isAdmin && (
  <>
    <div className="border-t border-white/10 my-1" />
    <Link href="/settings/noospheres" className="...">
      Noospheres
    </Link>
    <Link href="/settings/team" className="...">
      Team Settings
    </Link>
  </>
)}
```

---

## Phase 5: Noosphere Management Page (`/settings/noospheres`)

Admin-only. Shows all workspaces with stats, rename, archive controls.

### Custom Hook: `useWorkspaceStats`

For each workspace, fetch its stats from `GET /stats` (via the API client
with that workspace's ID). This requires fetching stats per-workspace.

To avoid N parallel requests on page load, load stats lazily on row expand
or use the `stats` embedded in the workspace doc if you denormalize them
(the schema has `stats: { documentCount, entityCount, domainCount }` on the
workspace doc — use that if available, it's cheapest).

### Page Component

```tsx
// app/settings/noospheres/page.tsx
'use client'
import { useState } from 'react'
import { useWorkspaces } from '@/lib/hooks/use-workspaces'
import { useAuth } from '@/lib/auth-context'
import { updateWorkspace, archiveWorkspace } from '@/lib/api'
import { redirect } from 'next/navigation'

export default function NoospheresPage() {
  const { session } = useAuth()
  const { workspaces, loading } = useWorkspaces()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  // Admin guard
  if (session && session.role !== 'admin') redirect('/')

  return (
    <div className="max-w-2xl mx-auto py-10 px-6">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-white font-mono text-sm tracking-widest">NOOSPHERES</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 text-xs font-mono border border-teal-400/30
                     text-teal-400 rounded hover:bg-teal-400/10"
        >
          + New Noosphere
        </button>
      </div>

      {loading ? (
        <p className="text-white/30 font-mono text-xs">Loading...</p>
      ) : (
        <div className="space-y-2">
          {workspaces.map(ws => (
            <WorkspaceRow
              key={ws.id}
              workspace={ws}
              onRename={(id, name) => updateWorkspace(id, name)}
              onArchive={(id) => archiveWorkspace(id)}
            />
          ))}
        </div>
      )}

      {showCreate && (
        <CreateNoosphereModal
          onClose={() => setShowCreate(false)}
          onCreated={() => setShowCreate(false)}
        />
      )}
    </div>
  )
}

function WorkspaceRow({ workspace, onRename, onArchive }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(workspace.name)
  const [confirming, setConfirming] = useState(false)

  async function handleRename() {
    if (name.trim() && name !== workspace.name) {
      await onRename(workspace.id, name.trim())
    }
    setEditing(false)
  }

  return (
    <div className="flex items-center justify-between p-3 rounded border border-white/10
                    bg-white/2 hover:bg-white/5 transition-colors group">
      <div className="flex-1 min-w-0">
        {editing ? (
          <input
            autoFocus
            value={name}
            onChange={e => setName(e.target.value)}
            onBlur={handleRename}
            onKeyDown={e => { if (e.key === 'Enter') handleRename() }}
            className="bg-transparent border-b border-teal-400/50 text-white text-xs
                       font-mono focus:outline-none w-full"
          />
        ) : (
          <span className="text-white text-xs font-mono">{workspace.name}</span>
        )}
        {/* Stats from workspace doc */}
        <div className="flex gap-3 mt-0.5">
          <span className="text-white/20 text-[10px] font-mono">
            {workspace.stats?.documentCount ?? 0} docs
          </span>
          <span className="text-white/20 text-[10px] font-mono">
            {workspace.stats?.entityCount ?? 0} entities
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => setEditing(true)}
          className="text-white/30 hover:text-white/70 text-xs font-mono px-2 py-1"
        >
          Rename
        </button>
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            className="text-white/20 hover:text-red-400/70 text-xs font-mono px-2 py-1"
          >
            Archive
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <span className="text-white/30 text-[10px] font-mono">Sure?</span>
            <button
              onClick={() => onArchive(workspace.id)}
              className="text-red-400 text-xs font-mono px-2 py-1"
            >
              Yes
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-white/30 text-xs font-mono px-2 py-1"
            >
              No
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
```

---

## Phase 6: Team Management Page (`/settings/team`)

Admin-only. Members list, invite creation, invite revocation, role display.

### Custom Hooks

```typescript
// lib/hooks/use-members.ts
import { useState, useEffect } from 'react'
import { collection, onSnapshot } from 'firebase/firestore'
import { db } from '@/lib/firebase'
import { useAuth } from '@/lib/auth-context'

export function useMembers() {
  const { session } = useAuth()
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!session?.orgId) return

    // Members are a subcollection under the org document
    const membersRef = collection(db, 'organizations', session.orgId, 'members')
    const unsubscribe = onSnapshot(membersRef, (snapshot) => {
      setMembers(snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() })))
      setLoading(false)
    })
    return () => unsubscribe()
  }, [session?.orgId])

  return { members, loading }
}
```

```typescript
// lib/hooks/use-invites.ts
import { useState, useEffect } from 'react'
import { getInvites } from '@/lib/api'   // GET /invites

export function useInvites() {
  const [invites, setInvites] = useState([])
  const [loading, setLoading] = useState(true)

  async function load() {
    const data = await getInvites()
    setInvites(data)
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  return { invites, loading, refresh: load }
}
```

Note: Invites use the REST API (`GET /invites`) not Firestore directly —
they're backend-managed and security rules prevent client reads. Refresh
after create/revoke actions.

### Team Page Component

```tsx
// app/settings/team/page.tsx
'use client'
import { useState } from 'react'
import { useAuth } from '@/lib/auth-context'
import { useMembers } from '@/lib/hooks/use-members'
import { useInvites } from '@/lib/hooks/use-invites'
import { createInvite, revokeInvite } from '@/lib/api'
import { redirect } from 'next/navigation'

const ROLE_LABELS = {
  admin: 'Admin',
  editor: 'Editor',
  viewer: 'Viewer',
}

export default function TeamPage() {
  const { session } = useAuth()
  const { members, loading: membersLoading } = useMembers()
  const { invites, loading: invitesLoading, refresh } = useInvites()
  const [showInvite, setShowInvite] = useState(false)

  if (session && session.role !== 'admin') redirect('/')

  return (
    <div className="max-w-2xl mx-auto py-10 px-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-white font-mono text-sm tracking-widest">TEAM</h1>
        <button
          onClick={() => setShowInvite(true)}
          className="px-3 py-1.5 text-xs font-mono border border-teal-400/30
                     text-teal-400 rounded hover:bg-teal-400/10"
        >
          + Invite someone
        </button>
      </div>

      {/* Members */}
      <section className="mb-8">
        <h2 className="text-white/40 text-[10px] font-mono tracking-widest mb-3">
          MEMBERS
        </h2>
        {membersLoading ? (
          <p className="text-white/20 text-xs font-mono">Loading...</p>
        ) : (
          <div className="space-y-1">
            {members.map(member => (
              <MemberRow
                key={member.id}
                member={member}
                isSelf={member.id === session?.uid}
              />
            ))}
          </div>
        )}
      </section>

      {/* Pending Invites */}
      <section>
        <h2 className="text-white/40 text-[10px] font-mono tracking-widest mb-3">
          PENDING INVITES
        </h2>
        {invitesLoading ? (
          <p className="text-white/20 text-xs font-mono">Loading...</p>
        ) : invites.length === 0 ? (
          <p className="text-white/20 text-xs font-mono">No pending invites</p>
        ) : (
          <div className="space-y-1">
            {invites.map(invite => (
              <InviteRow
                key={invite.id}
                invite={invite}
                onRevoke={async () => {
                  await revokeInvite(invite.id)
                  refresh()
                }}
              />
            ))}
          </div>
        )}
      </section>

      {/* Invite modal */}
      {showInvite && (
        <InviteModal
          onClose={() => setShowInvite(false)}
          onCreated={() => { setShowInvite(false); refresh() }}
        />
      )}
    </div>
  )
}

function MemberRow({ member, isSelf }) {
  return (
    <div className="flex items-center justify-between p-3 rounded border border-white/10
                    bg-white/2">
      <div>
        <span className="text-white text-xs font-mono">{member.email}</span>
        {isSelf && (
          <span className="ml-2 text-white/20 text-[10px] font-mono">(you)</span>
        )}
      </div>
      <span className="text-white/40 text-[10px] font-mono">
        {ROLE_LABELS[member.role] ?? member.role}
      </span>
    </div>
  )
}

function InviteRow({ invite, onRevoke }) {
  const [confirming, setConfirming] = useState(false)
  const age = Math.floor((Date.now() - new Date(invite.createdAt).getTime()) / 86400000)

  return (
    <div className="flex items-center justify-between p-3 rounded border border-white/10
                    bg-white/2 group">
      <div>
        <span className="text-white/70 text-xs font-mono">{invite.email}</span>
        <div className="flex gap-3 mt-0.5">
          <span className="text-white/20 text-[10px] font-mono">
            {ROLE_LABELS[invite.role]}
          </span>
          <span className="text-white/20 text-[10px] font-mono">
            Invited {age === 0 ? 'today' : `${age}d ago`}
          </span>
        </div>
      </div>
      {!confirming ? (
        <button
          onClick={() => setConfirming(true)}
          className="opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400/70
                     text-xs font-mono px-2 py-1 transition-all"
        >
          Revoke
        </button>
      ) : (
        <div className="flex items-center gap-1">
          <span className="text-white/30 text-[10px] font-mono">Sure?</span>
          <button onClick={onRevoke} className="text-red-400 text-xs font-mono px-2 py-1">
            Yes
          </button>
          <button onClick={() => setConfirming(false)}
            className="text-white/30 text-xs font-mono px-2 py-1">
            No
          </button>
        </div>
      )}
    </div>
  )
}
```

### Invite Modal

```tsx
// components/invite-modal.tsx
'use client'
import { useState } from 'react'
import { createInvite } from '@/lib/api'

export function InviteModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'editor' | 'viewer'>('editor')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const appUrl = typeof window !== 'undefined' ? window.location.origin : ''

  async function handleInvite() {
    if (!email.trim()) { setError('Email required'); return }
    setLoading(true)
    try {
      await createInvite(email.trim().toLowerCase(), role)
      setSuccess(true)
    } catch (e) {
      setError('Failed to create invite')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-[#080d14] border border-white/10 rounded-lg p-6 w-96">

        {!success ? (
          <>
            <h2 className="text-white font-mono text-sm mb-5">Invite to your Noospheres</h2>

            <label className="block text-white/40 text-xs font-mono mb-1">Email</label>
            <input
              autoFocus
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleInvite()}
              placeholder="colleague@example.com"
              className="w-full bg-white/5 border border-white/10 rounded px-3 py-2
                         text-white text-sm font-mono mb-4 focus:outline-none
                         focus:border-teal-400/50"
            />

            <label className="block text-white/40 text-xs font-mono mb-2">Role</label>
            <div className="flex gap-3 mb-5">
              {(['editor', 'viewer'] as const).map(r => (
                <button
                  key={r}
                  onClick={() => setRole(r)}
                  className={`flex-1 py-2 px-3 rounded border text-xs font-mono transition-colors ${
                    role === r
                      ? 'border-teal-400/50 bg-teal-400/10 text-teal-400'
                      : 'border-white/10 text-white/40 hover:border-white/20'
                  }`}
                >
                  <div className="capitalize">{r}</div>
                  <div className="text-[10px] mt-0.5 font-normal">
                    {r === 'editor' ? 'Can upload & run pipeline' : 'Read-only access'}
                  </div>
                </button>
              ))}
            </div>

            {error && <p className="text-red-400 text-xs font-mono mb-3">{error}</p>}

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 text-xs font-mono text-white/40 hover:text-white/70"
              >
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={loading}
                className="px-4 py-2 text-xs font-mono bg-teal-400/10 border border-teal-400/30
                           text-teal-400 rounded hover:bg-teal-400/20 disabled:opacity-40"
              >
                {loading ? 'Sending...' : 'Create Invite'}
              </button>
            </div>
          </>
        ) : (
          /* Success state */
          <>
            <h2 className="text-white font-mono text-sm mb-3">Invite created</h2>
            <p className="text-white/50 text-xs font-mono mb-1">
              Share this URL with <span className="text-white/70">{email}</span>.
            </p>
            <p className="text-white/50 text-xs font-mono mb-5">
              When they sign in with Google, they'll automatically join your org.
            </p>
            <div className="flex gap-2 p-2 rounded border border-white/10 bg-white/5 mb-5">
              <code className="text-teal-400 text-xs flex-1 truncate">{appUrl}</code>
              <button
                onClick={() => navigator.clipboard.writeText(appUrl)}
                className="text-white/30 hover:text-white/70 text-xs font-mono"
              >
                Copy
              </button>
            </div>
            <div className="flex justify-end">
              <button
                onClick={onCreated}
                className="px-4 py-2 text-xs font-mono bg-teal-400/10 border border-teal-400/30
                           text-teal-400 rounded hover:bg-teal-400/20"
              >
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

---

## Phase 7: Settings Layout (`/settings/layout.tsx`)

Shared layout for settings pages with a back link and section nav.

```tsx
// app/settings/layout.tsx
'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  const pathname = usePathname()

  return (
    <div className="min-h-screen bg-[#01040a]">
      {/* Simple settings nav */}
      <div className="flex items-center gap-4 px-6 py-3 border-b border-white/10">
        <Link
          href="/"
          className="text-white/30 hover:text-white/70 text-xs font-mono transition-colors"
        >
          ← Back
        </Link>
        <span className="text-white/10">|</span>
        {session?.role === 'admin' && (
          <>
            <Link
              href="/settings/noospheres"
              className={`text-xs font-mono transition-colors ${
                pathname === '/settings/noospheres'
                  ? 'text-teal-400'
                  : 'text-white/40 hover:text-white/70'
              }`}
            >
              Noospheres
            </Link>
            <Link
              href="/settings/team"
              className={`text-xs font-mono transition-colors ${
                pathname === '/settings/team'
                  ? 'text-teal-400'
                  : 'text-white/40 hover:text-white/70'
              }`}
            >
              Team
            </Link>
          </>
        )}
      </div>

      <div>{children}</div>
    </div>
  )
}
```

---

## API Client Additions (`lib/api.ts`)

Add these functions to the existing api.ts:

```typescript
// Workspaces
export async function createWorkspace(name: string, description: string) {
  return apiPost('/workspaces', { name, description })
}

export async function updateWorkspace(id: string, name: string) {
  return apiPatch(`/workspaces/${id}`, { name })
}

export async function archiveWorkspace(id: string) {
  return apiDelete(`/workspaces/${id}`)
}

// Invites
export async function getInvites() {
  return apiGet('/invites')
}

export async function createInvite(email: string, role: string) {
  return apiPost('/invites', { email, role })
}

export async function revokeInvite(id: string) {
  return apiDelete(`/invites/${id}`)
}
```

---

## Environment Variable

Add to `.env.local` and Vercel/Cloud Run env:

```
NEXT_PUBLIC_MAGOS_WORKSPACE_ID=<the hardcoded demo workspace ID>
```

This is used in the switcher to always show the Magos Noosphere entry and in
the workspace layout to allow access without validation. Set it to the actual
Firestore document ID of the demo workspace once created.

---

## Implementation Order

### Step 1 — Route restructure (1 day)
1. Create `app/n/[noosphereId]/layout.tsx` with workspace sync logic
2. Move existing page files into `app/n/[noosphereId]/` subdirectories
3. Rename `/viz` → `/orrery` in the file and update the iframe src
4. Update `app/page.tsx` to be redirect-only
5. Test: navigate to `/n/WORKSPACE_ID/upload` directly — should work
6. Test: navigate to `/` — should redirect to last workspace

### Step 2 — NavBar (0.5 days)
1. Create `components/nav-bar.tsx` with tab links using `currentNoosphereId` prop
2. Update `app/n/[noosphereId]/layout.tsx` to render NavBar
3. Remove nav from root `app/layout.tsx` (or keep for non-workspace pages)
4. Test: tab links update correctly, active state works

### Step 3 — Noosphere Switcher (1 day)
1. Create `lib/hooks/use-workspaces.ts` with Firestore `onSnapshot`
2. Create `components/noosphere-switcher.tsx`
3. Create `components/create-noosphere-modal.tsx`
4. Wire switcher into NavBar
5. Create `lib/navigation.ts` with `switchNoosphere()`
6. Test: switch between workspaces — URL changes, data reloads
7. Test: create a new workspace — appears in switcher immediately (Firestore listener)

### Step 4 — UserMenu settings links (0.5 days)
1. Add admin-gated links to Team and Noospheres in existing `user-menu.tsx`
2. Test: admin sees links, non-admin does not

### Step 5 — Settings layout + Noospheres page (1 day)
1. Create `app/settings/layout.tsx`
2. Create `app/settings/noospheres/page.tsx` with `WorkspaceRow` component
3. Add rename (inline edit on blur) and archive (confirm pattern) actions
4. Test: rename workspace — appears immediately in switcher (Firestore listener)
5. Test: archive workspace — disappears from switcher

### Step 6 — Team page + invite flow (1 day)
1. Create `lib/hooks/use-members.ts` with Firestore `onSnapshot`
2. Create `lib/hooks/use-invites.ts` with REST polling
3. Create `app/settings/team/page.tsx`
4. Create `components/invite-modal.tsx` with success state
5. Test full invite flow: create invite → sign in with different account → verify org membership

### Step 7 — Auth enable (0.5 days)
1. After all pages work and invite flow is tested end-to-end:
   `gcloud run services update orrery-orchestrator --update-env-vars AUTH_REQUIRED=true`
2. Test: unauthenticated requests return 401
3. Test: authenticated requests work normally

---

## Gotchas

**`useParams` is client-only.** The `[noosphereId]` layout must be a `'use client'`
component to use `useParams`. Server components access params via the `params`
prop — but since we need auth context (also client-side), the layout is already
a client component.

**Firestore `onSnapshot` composite index.** The query
`where('orgId', '==', ...).where('status', '!=', 'archived')` needs a composite
index. Alternatively, filter `status !== 'archived'` client-side after the
snapshot (simpler, works for small workspace counts).

**`setApiWorkspaceId` race condition.** The layout's `useEffect` that calls
`setApiWorkspaceId(noosphereId)` runs after first render. Any API call that
fires on mount in a child page may use the old workspace ID. Solution: pass
`workspaceId` explicitly to API calls in child pages, or use `useParams`
directly in page components for the initial fetch.

**Archived workspaces in URL.** A user can navigate to an archived workspace
via a bookmarked URL. The layout's validation check (`isValid`) will fail and
redirect them — but only if the workspace doc has `status: 'archived'`. The
Firestore listener won't include archived workspaces so `session.workspaces`
won't have it either. The redirect to fallback workspace handles this correctly.

**Magos Noosphere write guard.** When `noosphereId === MAGOS_WORKSPACE_ID`,
the layout should set a flag in context (e.g., `isDemo: true`) that upload,
pipeline trigger, and normalization components read to hide/disable their
controls. The backend security rules enforce this too (the demo workspace has
no editors), but the frontend should hide the UI rather than just letting
requests fail.
