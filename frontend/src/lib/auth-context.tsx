"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { type User } from "firebase/auth";
import { onAuthChange, signInWithGoogle, signOutUser, setupSession, type SessionInfo } from "./firebase";
import { setApiWorkspaceId } from "./api";

const API_URL = "/api";

interface AuthContextType {
  user: User | null;
  loading: boolean;
  session: SessionInfo | null;
  workspaceId: string | null;
  setWorkspaceId: (id: string) => void;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  session: null,
  workspaceId: null,
  setWorkspaceId: () => {},
  signIn: async () => {},
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [workspaceId, _setWorkspaceId] = useState<string | null>(null);

  // Keep API module in sync with workspace ID
  const setWorkspaceId = useCallback((id: string) => {
    _setWorkspaceId(id);
    setApiWorkspaceId(id);
  }, []);

  // Provision session when user signs in
  const provisionSession = useCallback(async (firebaseUser: User | null) => {
    if (!firebaseUser) {
      setSession(null);
      _setWorkspaceId(null);
      setApiWorkspaceId(null);
      return;
    }

    try {
      const sess = await setupSession(API_URL);
      if (sess) {
        setSession(sess);
        // Default to first workspace if none selected
        if (sess.workspaces.length > 0) {
          const defaultWs = sess.workspaces[0].id;
          _setWorkspaceId(defaultWs);
          setApiWorkspaceId(defaultWs);
        }
      }
    } catch (error) {
      console.error("Session setup failed:", error);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = onAuthChange((firebaseUser) => {
      setUser(firebaseUser);
      setLoading(false);
      provisionSession(firebaseUser);
    });
    return unsubscribe;
  }, [provisionSession]);

  const signIn = async () => {
    try {
      await signInWithGoogle();
    } catch (error) {
      console.error("Sign in failed:", error);
    }
  };

  const signOut = async () => {
    try {
      await signOutUser();
      setSession(null);
      _setWorkspaceId(null);
      setApiWorkspaceId(null);
    } catch (error) {
      console.error("Sign out failed:", error);
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, session, workspaceId, setWorkspaceId, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
