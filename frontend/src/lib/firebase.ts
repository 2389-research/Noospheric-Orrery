import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, type User, type Auth } from "firebase/auth";

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
