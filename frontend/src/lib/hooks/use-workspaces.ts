"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth-context";
import { api } from "@/lib/api";

export interface Workspace {
  id: string;
  name: string;
  description?: string;
  status?: string;
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
    } catch (err) {
      console.warn("Failed to fetch workspaces:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!session?.orgId) return;
    refresh();
  }, [session?.orgId, refresh]);

  return { workspaces, loading, refresh };
}
