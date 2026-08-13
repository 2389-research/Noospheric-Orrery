"use client";

// Persistent, minimizable tutorial guidance panel — mounted once in the noosphere layout so
// it survives navigation across Upload/Pipeline/Documents/etc. Only renders when this
// workspace was entered via the /tutorial flow (see the "tutorial:{id}:enabled" flag set by
// frontend/src/app/tutorial/page.tsx). See docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md,
// "Revision 2 — persistent cross-page panel" and "Revision 3 — Documents → Orrery handoff".
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

// A document detail route looks like /n/{id}/documents/{docId} — one segment past the
// plain Documents list route, which is what "opened a document" means here.
function isDocumentDetailPath(pathname: string) {
  return /\/documents\/[^/]+$/.test(pathname);
}

export function TutorialPanel({ noosphereId }: { noosphereId: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [enabled, setEnabled] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const { quests, documentCount, markVisitedDocuments, markOpenedDocument, markVisitedOrrery } =
    useTutorialQuests(noosphereId);

  useEffect(() => {
    setEnabled(localStorage.getItem(enabledKey(noosphereId)) === "1");
    const saved = localStorage.getItem(expandedKey(noosphereId));
    if (saved !== null) setExpanded(saved === "1");
  }, [noosphereId]);

  // Mark "visited Documents" the instant the user lands on the list with ≥1 document —
  // does NOT navigate anywhere or hide the list, just records the visit.
  useEffect(() => {
    if (pathname.endsWith("/documents") && documentCount > 0) markVisitedDocuments();
  }, [pathname, documentCount, markVisitedDocuments]);

  // Mark "opened a document" when the user actually drills into one from that list.
  useEffect(() => {
    if (isDocumentDetailPath(pathname)) markOpenedDocument();
  }, [pathname, markOpenedDocument]);

  // Mark "visited Orrery" on arrival at the real galaxy view.
  useEffect(() => {
    if (pathname.endsWith("/orrery")) markVisitedOrrery();
  }, [pathname, markVisitedOrrery]);

  if (!enabled) return null;

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    localStorage.setItem(expandedKey(noosphereId), next ? "1" : "0");
  };

  const requiredQuests = quests.filter((q) => !q.optional);
  const optionalQuests = quests.filter((q) => q.optional);
  const activeQuest = requiredQuests.find((q) => !q.done) ?? null;
  const onUpload = pathname.endsWith("/upload");
  const onDocumentsList = pathname.endsWith("/documents");

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
              {!onDocumentsList && (
                <button
                  className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40"
                  onClick={() => router.push(`/n/${noosphereId}/documents`)}
                >
                  Go to Documents
                </button>
              )}
            </div>
          )}

          {activeQuest?.id === "open_document" && (
            <div className="space-y-2">
              <p className="text-xs">
                {onDocumentsList
                  ? "Click the file you just added to see everything it extracted."
                  : "Back in Documents, click the file you just added."}
              </p>
              {!onDocumentsList && (
                <button
                  className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40"
                  onClick={() => router.push(`/n/${noosphereId}/documents`)}
                >
                  Go to Documents
                </button>
              )}
            </div>
          )}

          {activeQuest?.id === "view_orrery" && (
            <div className="space-y-2">
              <p className="text-xs">
                Now see it live in the Orrery — every entity you just met, as a star.
              </p>
              {!pathname.endsWith("/orrery") && (
                <button
                  className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40"
                  onClick={() => router.push(`/n/${noosphereId}/orrery`)}
                >
                  Go to Orrery
                </button>
              )}
            </div>
          )}

          {activeQuest &&
            !["ingest", "visit_documents", "open_document", "view_orrery"].includes(activeQuest.id) && (
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

          {optionalQuests.length > 0 && (
            <div className="space-y-1 pt-2 border-t border-border/30">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground/70">Optional</p>
              {optionalQuests.map((q) => (
                <div key={q.id} className="flex items-center gap-2 text-[11px]">
                  <span className={q.done ? "text-emerald-400" : "text-muted-foreground/50"}>
                    {q.done ? "✓" : "○"}
                  </span>
                  <span className={q.done ? "text-foreground" : "text-muted-foreground"}>{q.title}</span>
                </div>
              ))}
            </div>
          )}

          <div className="space-y-1 pt-2 border-t border-border/30">
            {requiredQuests.map((q) => (
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
