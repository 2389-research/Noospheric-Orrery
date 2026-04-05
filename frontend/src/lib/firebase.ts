import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, type User, type Auth } from "firebase/auth";
import { getFirestore, doc, onSnapshot, type Firestore } from "firebase/firestore";

const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE || "firebase";
const IS_NOOP = AUTH_MODE === "noop";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || "noospheric-orrery.firebaseapp.com",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || "noospheric-orrery",
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || "noospheric-orrery.firebasestorage.app",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || "",
};

// Lazy initialization — only in browser, only in firebase mode
let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;
const googleProvider = new GoogleAuthProvider();

function getFirebaseAuth(): Auth | null {
  if (typeof window === "undefined") return null;
  if (IS_NOOP) return null;
  if (!firebaseConfig.apiKey) return null;
  if (!_app) {
    _app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0];
  }
  if (!_auth) {
    _auth = getAuth(_app);
  }
  return _auth;
}

// Mock user for noop mode — satisfies the User type shape used by the UI
const NOOP_USER = {
  uid: "local-dev",
  email: "dev@localhost",
  displayName: "Local Dev",
  photoURL: null,
  emailVerified: true,
  isAnonymous: false,
  metadata: {},
  providerData: [],
  providerId: "local",
  refreshToken: "",
  tenantId: null,
  delete: async () => {},
  getIdToken: async () => "",
  getIdTokenResult: async () => ({} as never),
  reload: async () => {},
  toJSON: () => ({}),
} as unknown as User;

export async function signInWithGoogle() {
  if (IS_NOOP) return NOOP_USER;
  const auth = getFirebaseAuth();
  if (!auth) throw new Error("Firebase not configured");
  const result = await signInWithPopup(auth, googleProvider);
  return result.user;
}

export async function signOutUser() {
  if (IS_NOOP) return;
  const auth = getFirebaseAuth();
  if (auth) await signOut(auth);
}

export function onAuthChange(callback: (user: User | null) => void) {
  if (IS_NOOP) {
    // Noop mode — immediately "sign in" as local dev user
    callback(NOOP_USER);
    return () => {};
  }
  const auth = getFirebaseAuth();
  if (!auth) {
    callback(null);
    return () => {};
  }
  return onAuthStateChanged(auth, callback);
}

export async function getAuthToken(): Promise<string | null> {
  if (IS_NOOP) return null; // No token needed — backend has AUTH_REQUIRED=false
  const auth = getFirebaseAuth();
  if (!auth) return null;
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken();
}

export function getFirestoreDb(): Firestore | null {
  if (typeof window === "undefined") return null;
  if (IS_NOOP) return null; // No Firestore in local mode
  if (!_app) return null;
  return getFirestore(_app);
}

export interface SessionInfo {
  orgId: string;
  role: string;
  workspaces: { id: string; name: string }[];
}

/**
 * Call after sign-in to provision org/workspace and set up token refresh watcher.
 * In noop mode, calls the API without auth headers (backend uses DEV_USER).
 */
export async function setupSession(apiUrl: string): Promise<SessionInfo | null> {
  if (IS_NOOP) {
    // Noop mode — call provision without auth headers
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

  // Firebase mode — need auth token
  const token = await getAuthToken();
  if (!token) return null;

  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };

  // 1. Check for pending invite
  try {
    await fetch(`${apiUrl}/auth/accept-invite`, { method: "POST", headers });
  } catch {
    // Invite check is best-effort
  }

  // 2. Provision (creates org if new, returns existing if returning)
  const res = await fetch(`${apiUrl}/auth/provision`, { method: "POST", headers });
  if (!res.ok) return null;
  const session: SessionInfo = await res.json();

  // 3. Start token refresh watcher
  const auth = getFirebaseAuth();
  const db = getFirestoreDb();
  if (auth?.currentUser && db) {
    watchTokenRefresh(auth.currentUser.uid, db);
  }

  return session;
}

let _tokenRefreshUnsub: (() => void) | null = null;

export function watchTokenRefresh(uid: string, db: Firestore): void {
  if (_tokenRefreshUnsub) {
    _tokenRefreshUnsub();
  }

  const userDocRef = doc(db, "users", uid);
  _tokenRefreshUnsub = onSnapshot(userDocRef, async (snap) => {
    if (snap.exists()) {
      const auth = getFirebaseAuth();
      if (auth?.currentUser) {
        await auth.currentUser.getIdToken(true);
        console.log("[auth] Token refreshed after claims update");
      }
    }
  });
}
