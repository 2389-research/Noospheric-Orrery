"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useWorkspaces } from "@/lib/hooks/use-workspaces";
import { setApiWorkspaceId } from "@/lib/api";
import { NavBar } from "@/components/nav-bar";
import { DemoModeContext } from "@/lib/hooks/use-demo-mode";

const MAGOS_ID = process.env.NEXT_PUBLIC_MAGOS_WORKSPACE_ID;
const IS_NOOP = process.env.NEXT_PUBLIC_AUTH_MODE === "noop";

export default function NoosphereLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { noosphereId } = useParams<{ noosphereId: string }>();
  const { session, setWorkspaceId } = useAuth();
  const { workspaces } = useWorkspaces();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  const isDemo = noosphereId === MAGOS_ID;

  useEffect(() => {
    if (!noosphereId || !session) return;

    // Check both session workspaces (initial) and live workspace list (API)
    const isValid =
      IS_NOOP ||
      session.workspaces.some((w) => w.id === noosphereId) ||
      workspaces.some((w) => w.id === noosphereId) ||
      isDemo;

    if (!isValid) {
      const fallback = session.workspaces[0]?.id;
      if (fallback) router.replace(`/n/${fallback}/upload`);
      return;
    }

    setWorkspaceId(noosphereId);
    setApiWorkspaceId(noosphereId);
    localStorage.setItem("lastWorkspaceId", noosphereId);
    setReady(true);
  }, [noosphereId, session, workspaces, setWorkspaceId, router, isDemo]);

  if (!ready) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-[10px] text-muted-foreground/40 font-mono">loading noosphere...</span>
      </div>
    );
  }

  return (
    <DemoModeContext.Provider value={isDemo}>
      <NavBar currentNoosphereId={noosphereId} isDemo={isDemo} />
      {isDemo && (
        <div className="px-6 py-1.5 bg-amber-500/5 border-b border-amber-500/10">
          <span className="text-[10px] text-amber-400/60 font-mono">
            ✦ This is a shared, read-only Noosphere · Your data is in your own workspaces
          </span>
        </div>
      )}
      <main className="p-6">{children}</main>
    </DemoModeContext.Provider>
  );
}
