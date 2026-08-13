"use client";

// Persistent, minimizable tutorial guidance panel — mounted once in the noosphere layout so
// it survives navigation across Upload/Pipeline/Documents/etc. Only renders when this
// workspace was entered via the /tutorial flow (see the "tutorial:{id}:enabled" flag set by
// frontend/src/app/tutorial/page.tsx). See docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md,
// "Revision 2 — persistent cross-page panel".
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTutorialQuests } from "@/lib/hooks/use-tutorial-quests";

const SAMPLE_FILES = ["business-001.txt", "politics-296.txt", "sport-056.txt"];

function enabledKey(id: string) {
  return `tutorial:${id}:enabled`;
}
function expandedKey(id: string) {
  return `tutorial:${id}:panelExpanded`;
}

export function TutorialPanel({ noosphereId }: { noosphereId: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [enabled, setEnabled] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const { quests, documentCount, markVisitedDocuments } = useTutorialQuests(noosphereId);

  useEffect(() => {
    setEnabled(localStorage.getItem(enabledKey(noosphereId)) === "1");
    const saved = localStorage.getItem(expandedKey(noosphereId));
    if (saved !== null) setExpanded(saved === "1");
  }, [noosphereId]);

  // Mark "visited Documents" the instant the user lands on that page with ≥1 document.
  useEffect(() => {
    if (pathname.endsWith("/documents") && documentCount > 0) markVisitedDocuments();
  }, [pathname, documentCount, markVisitedDocuments]);

  if (!enabled) return null;

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    localStorage.setItem(expandedKey(noosphereId), next ? "1" : "0");
  };

  const activeQuest = quests.find((q) => !q.done) ?? null;
  const onUpload = pathname.endsWith("/upload");

  return (
    <div className="fixed bottom-4 left-4 z-50 w-72">
      {!expanded ? (
        <button
          onClick={toggle}
          className="text-xs px-3 py-2 rounded-full border border-border/50 bg-card/90 backdrop-blur hover:bg-accent/40 shadow-lg"
        >
          ✦ Tutorial {activeQuest ? "· " + activeQuest.title : "· complete"}
        </button>
      ) : (
        <div className="rounded border border-border/50 bg-card/90 backdrop-blur shadow-lg p-3 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
              ✦ Tutorial
            </span>
            <button onClick={toggle} className="text-xs text-muted-foreground hover:text-foreground">
              minimize
            </button>
          </div>

          {activeQuest?.id === "ingest" && (
            <div className="space-y-2">
              <p className="text-xs">
                {onUpload
                  ? "Drag one of these onto the ingestion box below to get started."
                  : "Head to Upload, then drag one of these onto the ingestion box."}
              </p>
              <div className="flex gap-2">
                {SAMPLE_FILES.map((name) => (
                  <div
                    key={name}
                    draggable={onUpload}
                    onDragStart={(e) => e.dataTransfer.setData("text/tutorial-sample", name)}
                    className={`flex flex-col items-center gap-1 w-14 p-1.5 rounded border text-center ${
                      onUpload ? "border-border/50 cursor-grab hover:bg-accent/40" : "border-border/20 opacity-50"
                    }`}
                    title={onUpload ? `Drag to ingest ${name}` : "Go to Upload to drag this in"}
                  >
                    <span className="text-lg">📄</span>
                    <span className="text-[9px] text-muted-foreground truncate w-full">
                      {name.split("-")[0]}
                    </span>
                  </div>
                ))}
              </div>
              {!onUpload && (
                <button
                  className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40"
                  onClick={() => router.push(`/n/${noosphereId}/upload`)}
                >
                  Go to Upload
                </button>
              )}
            </div>
          )}

          {activeQuest?.id === "visit_documents" && (
            <div className="space-y-2">
              <p className="text-xs">Nice — that&apos;s ingested. Now go check it out in Documents.</p>
              {!pathname.endsWith("/documents") && (
                <button
                  className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40"
                  onClick={() => router.push(`/n/${noosphereId}/documents`)}
                >
                  Go to Documents
                </button>
              )}
            </div>
          )}

          {activeQuest && activeQuest.id !== "ingest" && activeQuest.id !== "visit_documents" && (
            <p className="text-xs text-muted-foreground">
              Next: <span className="text-foreground">{activeQuest.title}</span>
            </p>
          )}

          {!activeQuest && (
            <p className="text-xs text-muted-foreground">
              All caught up — visit <code>/n/{noosphereId}/tutorial</code> for search, the galaxy
              map, and building your own domain.
            </p>
          )}

          <div className="space-y-1 pt-2 border-t border-border/30">
            {quests.map((q) => (
              <div key={q.id} className="flex items-center gap-2 text-[11px]">
                <span className={q.done ? "text-emerald-400" : "text-muted-foreground/50"}>
                  {q.done ? "✓" : "○"}
                </span>
                <span className={q.done ? "text-foreground" : "text-muted-foreground"}>{q.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
