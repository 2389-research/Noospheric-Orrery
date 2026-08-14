"use client";

// Persistent, minimizable tutorial guidance panel — mounted once in the noosphere layout so
// it survives navigation across Upload/Pipeline/Documents/etc. Only renders when this
// workspace was entered via the /tutorial flow (see the "tutorial:{id}:enabled" flag set by
// frontend/src/app/tutorial/page.tsx). See docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md,
// "Revision 2 — persistent cross-page panel", "Revision 3 — Documents → Orrery handoff", and
// "Revision 4 — add-more-files prompt after Orrery".
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTutorialQuests } from "@/lib/hooks/use-tutorial-quests";

const SAMPLE_FILES = ["entertainment-002.txt", "politics-296.txt", "sport-056.txt"];

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

function SampleIcons({ onUpload, ingestedTitles }: { onUpload: boolean; ingestedTitles: string[] }) {
  return (
    <div className="flex gap-2">
      {SAMPLE_FILES.map((name) => {
        const done = ingestedTitles.includes(name);
        const active = onUpload && !done;
        return (
          <div
            key={name}
            draggable={active}
            onDragStart={(e) => e.dataTransfer.setData("text/tutorial-sample", name)}
            className={`flex flex-col items-center gap-1 w-14 p-1.5 rounded border text-center ${
              done
                ? "border-border/20 opacity-40"
                : active
                  ? "border-border/50 cursor-grab hover:bg-accent/40"
                  : "border-border/20 opacity-50"
            }`}
            title={done ? `${name} — already ingested` : active ? `Drag to ingest ${name}` : "Go to Upload to drag this in"}
          >
            <span className="text-lg">📄</span>
            <span className="text-[9px] text-muted-foreground truncate w-full">{name.split("-")[0]}</span>
          </div>
        );
      })}
    </div>
  );
}

export function TutorialPanel({ noosphereId }: { noosphereId: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [enabled, setEnabled] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const {
    quests,
    documentCount,
    documentTitles,
    markVisitedDocuments,
    markOpenedDocument,
    markVisitedOrrery,
  } = useTutorialQuests(noosphereId);

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
  // Gated on documentCount > 0: nothing should advance if there's genuinely no document to
  // open — same reasoning as the visitedOrrery guard below.
  useEffect(() => {
    if (isDocumentDetailPath(pathname) && documentCount > 0) markOpenedDocument();
  }, [pathname, documentCount, markOpenedDocument]);

  // Mark "visited Orrery" on arrival at the real galaxy view — but only once something has
  // actually been ingested. Browsing to Orrery/Pipeline/etc. before the ingest quest is done is
  // always allowed (nothing here blocks navigation), it just must not silently advance the
  // tutorial past a step the user hasn't actually done yet.
  useEffect(() => {
    if (pathname.endsWith("/orrery") && documentCount > 0) markVisitedOrrery();
  }, [pathname, documentCount, markVisitedOrrery]);

  if (!enabled) return null;

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    localStorage.setItem(expandedKey(noosphereId), next ? "1" : "0");
  };

  const requiredQuests = quests.filter((q) => !q.optional);
  const optionalQuests = quests.filter((q) => q.optional);
  const activeQuest = requiredQuests.find((q) => !q.done) ?? null;
  const addMoreFiles = quests.find((q) => q.id === "add_more_files");
  const viewOrrery = quests.find((q) => q.id === "view_orrery");
  const onUpload = pathname.endsWith("/upload");
  const onDocumentsList = pathname.endsWith("/documents");

  // Once the user has seen the Orrery, offer "add more files?" as a standing, non-blocking
  // nudge — separate from the required-quest flow below. addMoreFiles.done is always false
  // (see use-tutorial-quests.ts), so this stays available indefinitely, not just until a
  // second file shows up — the point is you can always come back and add more.
  const showAddMorePrompt = viewOrrery?.done && !!addMoreFiles;

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
              <SampleIcons onUpload={onUpload} ingestedTitles={documentTitles} />
              <p className="text-xs text-muted-foreground">
                Or skip the samples and upload a document of your own.
              </p>
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

          {activeQuest?.id === "search" && (
            <div className="space-y-2">
              <p className="text-xs">
                {pathname.endsWith("/orrery")
                  ? "Try the search bar for a keyword from one of the documents you ingested."
                  : "Back in Orrery, try the search bar for a keyword from one of the documents you ingested."}
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

          {activeQuest?.id === "simmer" && (
            <div className="space-y-2">
              <p className="text-xs">
                {pathname.endsWith("/pipeline")
                  ? <>Click <strong>simmer general spec</strong> below to refine extraction.</>
                  : <>Head to Pipeline and click <strong>simmer general spec</strong> to refine extraction.</>}
              </p>
              <p className="text-xs text-muted-foreground">
                Tip: simmering works best with more to learn from — around 20 documents is a good
                point to start it. You can also just try it now on what you have.
              </p>
              {!pathname.endsWith("/pipeline") && (
                <button
                  className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40"
                  onClick={() => router.push(`/n/${noosphereId}/pipeline`)}
                >
                  Go to Pipeline
                </button>
              )}
            </div>
          )}

          {activeQuest &&
            !["ingest", "visit_documents", "open_document", "view_orrery", "search", "simmer"].includes(
              activeQuest.id,
            ) && (
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

          {showAddMorePrompt && (
            <div className="space-y-2 pt-2 border-t border-border/30">
              <p className="text-xs">
                Want to add more files? Same as before — drag one onto the ingestion box on Upload,
                or drop your own file into the matching section (or select a folder to upload).
              </p>
              <SampleIcons onUpload={onUpload} ingestedTitles={documentTitles} />
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
