"use client";

// Entry point for the onboarding tutorial. Always mints a fresh sandbox
// workspace and hands off to the workspace-scoped tutorial page — see
// docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function TutorialEntryPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ws = await api.createWorkspace(
          `Tutorial Sandbox — ${new Date().toISOString().slice(0, 16).replace("T", " ")}`,
          "Disposable sandbox created by the onboarding tutorial.",
        );
        // The persistent TutorialPanel (mounted in the noosphere layout) checks this flag
        // to decide whether to render on this workspace's pages.
        localStorage.setItem(`tutorial:${ws.workspaceId}:enabled`, "1");
        if (!cancelled) router.replace(`/n/${ws.workspaceId}/upload`);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to create sandbox");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex items-center justify-center h-screen bg-background">
      {error ? (
        <div className="text-center space-y-3">
          <p className="text-sm text-red-400">{error}</p>
          <button
            className="text-xs px-3 py-1.5 rounded border border-border/50 text-muted-foreground hover:text-foreground"
            onClick={() => window.location.reload()}
          >
            Retry
          </button>
        </div>
      ) : (
        <span className="text-[11px] text-muted-foreground/70 font-mono tracking-wider">
          calibrating a sandbox orrery...
        </span>
      )}
    </div>
  );
}
