import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, type User, type Auth } from "firebase/auth";
import { getFirestore, doc, onSnapshot, type Firestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || "noospheric-orrery.firebaseapp.com",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || "noospheric-orrery",
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || "noospheric-orrery.firebasestorage.app",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || "",
};

// Lazy initialization — only in browser
let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;
const googleProvider = new GoogleAuthProvider();

function getFirebaseAuth(): Auth | null {
  if (typeof window === "undefined") return null; // SSR — skip
  if (!firebaseConfig.apiKey) return null; // No config — skip
  if (!_app) {
    _app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0];
  }
  if (!_auth) {
    _auth = getAuth(_app);
  }
  return _auth;
}

export async function signInWithGoogle() {
  const auth = getFirebaseAuth();
  if (!auth) throw new Error("Firebase not configured");
  const result = await signInWithPopup(auth, googleProvider);
  return result.user;
}

export async function signOutUser() {
  const auth = getFirebaseAuth();
  if (auth) await signOut(auth);
}

export function onAuthChange(callback: (user: User | null) => void) {
  const auth = getFirebaseAuth();
  if (!auth) {
    // No Firebase — treat as unauthenticated
    callback(null);
    return () => {};
  }
  return onAuthStateChanged(auth, callback);
}

export async function getAuthToken(): Promise<string | null> {
  const auth = getFirebaseAuth();
  if (!auth) return null;
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken();
}

export function getFirestoreDb(): Firestore | null {
  if (typeof window === "undefined") return null;
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
 * Returns session info with orgId, role, and available workspaces.
 */
export async function setupSession(apiUrl: string): Promise<SessionInfo | null> {
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

/**
 * Watch users/{uid}/tokenRefreshAt sentinel doc.
 * When it changes (backend updated claims), force a token refresh.
 */
export function watchTokenRefresh(uid: string, db: Firestore): void {
  // Clean up previous watcher
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
