/**
 * Auth module — local mode (no external auth required).
 *
 * Exports the same interface as the original Firebase-backed version
 * so all consumers (auth-context, api, pages) work without changes.
 */

export interface AuthUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
  emailVerified: boolean;
  isAnonymous: boolean;
}

const LOCAL_USER: AuthUser = {
  uid: "local-dev",
  email: "dev@localhost",
  displayName: "Local Dev",
  photoURL: null,
  emailVerified: true,
  isAnonymous: false,
};

export async function signInWithGoogle(): Promise<AuthUser> {
  return LOCAL_USER;
}

export async function signOutUser(): Promise<void> {
  // no-op in local mode
}

export function onAuthChange(callback: (user: AuthUser | null) => void): () => void {
  // Immediately "sign in" as local user
  callback(LOCAL_USER);
  return () => {};
}

export async function getAuthToken(): Promise<string | null> {
  return null; // No token needed — backend has no auth requirement
}

export interface SessionInfo {
  orgId: string;
  role: string;
  workspaces: { id: string; name: string }[];
}

/**
 * Call /auth/provision to get workspace list.
 * Backend returns DEV_USER's session with local workspaces.
 */
export async function setupSession(apiUrl: string): Promise<SessionInfo | null> {
  try {
    const res = await fetch(`${apiUrl}/auth/provision`, { method: "POST" });
    if (!res.ok) {
      console.warn(`[auth] Provision failed (${res.status}), using default session`);
      return { orgId: "local", role: "admin", workspaces: [{ id: "default", name: "Default" }] };
    }
    return await res.json();
  } catch {
    // API not reachable — return hardcoded default
    return { orgId: "local", role: "admin", workspaces: [{ id: "default", name: "Default" }] };
  }
}
