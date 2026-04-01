"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { setApiWorkspaceId } from "@/lib/api";
import { NavBar } from "@/components/nav-bar";

export default function NoosphereLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { noosphereId } = useParams<{ noosphereId: string }>();
  const { session, setWorkspaceId } = useAuth();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!noosphereId || !session) return;

    // Validate this workspace belongs to the user's org (or is the demo workspace)
    const magosId = process.env.NEXT_PUBLIC_MAGOS_WORKSPACE_ID;
    const isValid =
      session.workspaces.some((w) => w.id === noosphereId) ||
      noosphereId === magosId;

    if (!isValid) {
      const fallback = session.workspaces[0]?.id;
      if (fallback) router.replace(`/n/${fallback}/upload`);
      return;
    }

    // Sync URL → context and API client
    setWorkspaceId(noosphereId);
    setApiWorkspaceId(noosphereId);
    localStorage.setItem("lastWorkspaceId", noosphereId);
    setReady(true);
  }, [noosphereId, session, setWorkspaceId, router]);

  if (!ready) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-[10px] text-muted-foreground/40 font-mono">loading noosphere...</span>
      </div>
    );
  }

  return (
    <>
      <NavBar currentNoosphereId={noosphereId} />
      <main className="p-6">{children}</main>
    </>
  );
}
