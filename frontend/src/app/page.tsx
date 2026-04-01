"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function RootPage() {
  const { session, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!session?.workspaces?.length) return;

    const lastId = typeof window !== "undefined" ? localStorage.getItem("lastWorkspaceId") : null;
    const valid = session.workspaces.find((w) => w.id === lastId);
    const target = valid ? lastId : session.workspaces[0].id;
    router.replace(`/n/${target}/upload`);
  }, [session, loading, router]);

  return null;
}
