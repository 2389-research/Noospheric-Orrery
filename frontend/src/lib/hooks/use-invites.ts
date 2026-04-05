"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";

export interface Invite {
  id: string;
  email: string;
  role: string;
  createdAt: string;
  status: string;
}

export function useInvites() {
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await api.getInvites();
      setInvites(data as Invite[]);
    } catch {
      // Silently fail — may not have permission
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { invites, loading, refresh: load };
}
