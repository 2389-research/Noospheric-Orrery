"use client";

import { useState, useEffect, useCallback } from "react";
import { collection, query, where, onSnapshot } from "firebase/firestore";
import { getFirestoreDb } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { api } from "@/lib/api";

export interface Workspace {
  id: string;
  name: string;
  orgId: string;
  description?: string;
  status?: string;
  isDemo?: boolean;
}

export function useWorkspaces() {
  const { session } = useAuth();
  const [workspaces, setWorkspaces] = useState<Workspace[]>(
    (session?.workspaces as Workspace[]) ?? [],
  );
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const ws = await api.listWorkspaces();
      setWorkspaces(ws.filter((w: Workspace) => w.status !== "archived"));
    } catch {
      // keep current
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!session?.orgId) return;

    const db = getFirestoreDb();
    if (!db) {
      // Noop/local mode — fetch from API
      refresh();
      return;
    }

    const q = query(
      collection(db, "workspaces"),
      where("orgId", "==", session.orgId),
    );

    const unsubscribe = onSnapshot(q, (snapshot) => {
      const ws = snapshot.docs
        .map((doc) => ({ id: doc.id, ...doc.data() }) as Workspace)
        .filter((ws) => ws.status !== "archived");

      setWorkspaces(ws);
      setLoading(false);
    });

    return () => unsubscribe();
  }, [session?.orgId, refresh]);

  return { workspaces, loading, refresh };
}
