"use client";

// Persistent, minimizable tutorial guidance panel — mounted once in the noosphere layout so
// it survives navigation across Upload/Pipeline/Documents/etc. Only renders when this
// workspace was entered via the /tutorial flow (see the "tutorial:{id}:enabled" flag set by
// frontend/src/app/tutorial/page.tsx). See docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md,
// "Revision 2 — persistent cross-page panel", "Revision 3 — Documents → Orrery handoff",
// "Revision 4 — add-more-files prompt after Orrery", "Revision 10 — cheering mascot", and
// "Revision 11 — always-present mascot, tips folded into its dialogue".
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTutorialQuests, type QuestId } from "@/lib/hooks/use-tutorial-quests";

const SAMPLE_FILES = ["entertainment-002.txt", "politics-296.txt", "sport-056.txt"];

// Reuses the same mascot art as the attract-mode screensaver (magos-overlay.tsx,
// frontend/public/mascot/) — a different use of the same asset set, not a new character.
// One pose per quest, used both while that quest is the active guidance AND for its
// completion cheer — the mascot doesn't switch identity, just expression.
const QUEST_POSE: Partial<Record<QuestId, string>> = {
  ingest: "pointing.png",
  visit_documents: "reading.png",
  open_document: "reading.png",
  view_orrery: "galxy.png",
  search: "pointing.png",
  classify: "thinking.png",
  simmer: "thinking.png",
  normalize: "thinking.png",
};
const IDLE_POSE = "happy.png";

const CHEER_LINE: Partial<Record<QuestId, string>> = {
  ingest: "New knowledge! Already? I'm delighted.",
  visit_documents: "There it is, filed and findable. I do love an organized shelf.",
  open_document: "Every name traced to its source — that's the good stuff.",
  view_orrery: "Look at it go. Your galaxy, growing. I could watch this forever.",
  search: "Found it. The graph knows what you're after.",
  classify: "New knowledge, sorted into its own little constellation. Marvelous.",
  simmer: "Spec refined. Sharper extraction from here on — more knowledge, better kept.",
  normalize: "Duplicates merged. Cleaner graph, same knowledge.",
};
const CHEER_MS = 4500;

function enabledKey(id: string) {
  return `tutorial:${id}:enabled`;
}
function expandedKey(id: string) {
  return `tutorial:${id}:panelExpanded`;
}
function introKey(id: string) {
  return `tutorial:${id}:introAcknowledged`;
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

interface Guidance {
  pose: string;
  lines: (string | React.ReactNode)[];
  button?: { label: string; onClick: () => void };
  showSampleIcons?: boolean;
}

export function TutorialPanel({ noosphereId }: { noosphereId: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [enabled, setEnabled] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [introAcknowledged, setIntroAcknowledged] = useState(false);
  const [cheerQuestId, setCheerQuestId] = useState<QuestId | null>(null);
  const prevDoneRef = useRef<Set<QuestId> | null>(null);
  const cheerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    setIntroAcknowledged(localStorage.getItem(introKey(noosphereId)) === "1");
  }, [noosphereId]);

  const acknowledgeIntro = () => {
    localStorage.setItem(introKey(noosphereId), "1");
    setIntroAcknowledged(true);
  };

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

  // Cheer whenever a quest transitions from not-done to done. prevDoneRef starts null so the
  // very first render (which may already have some quests done, e.g. re-entering with an
  // existing sandbox) doesn't fire a cheer for old news — only genuine transitions cheer.
  useEffect(() => {
    if (!enabled) return;
    const doneNow = new Set(quests.filter((q) => q.done).map((q) => q.id));
    if (prevDoneRef.current) {
      const justCompleted = quests.find((q) => q.done && !prevDoneRef.current!.has(q.id));
      if (justCompleted) {
        setCheerQuestId(justCompleted.id);
        if (cheerTimerRef.current) clearTimeout(cheerTimerRef.current);
        cheerTimerRef.current = setTimeout(() => setCheerQuestId(null), CHEER_MS);
      }
    }
    prevDoneRef.current = doneNow;
  }, [quests, enabled]);

  useEffect(() => {
    return () => {
      if (cheerTimerRef.current) clearTimeout(cheerTimerRef.current);
    };
  }, []);

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
  const onOrrery = pathname.endsWith("/orrery");
  const onPipeline = pathname.endsWith("/pipeline");

  // Once the user has seen the Orrery, offer "add more files?" as a standing, non-blocking
  // nudge — separate from the required-quest flow below. addMoreFiles.done is always false
  // (see use-tutorial-quests.ts), so this stays available indefinitely, not just until a
  // second file shows up — the point is you can always come back and add more.
  const showAddMorePrompt = viewOrrery?.done && !!addMoreFiles;

  // All guidance text — including tips that used to be separate paragraphs in the panel body
  // (e.g. the simmer document-count note) — now lives in the mascot's own dialogue lines.
  const guidance: Guidance = (() => {
    switch (activeQuest?.id) {
      case "ingest":
        if (!introAcknowledged) {
          return {
            pose: IDLE_POSE,
            lines: [
              "I'm Lex — a humble space priest, endlessly thirsty for human knowledge.",
              "Ready to help me build some?",
            ],
            button: { label: "Yes, let's build knowledge!", onClick: acknowledgeIntro },
          };
        }
        return {
          pose: QUEST_POSE.ingest!,
          lines: [
            onUpload
              ? "Drag one of these onto the ingestion box below to get started."
              : "Head to Upload, then drag one of these onto the ingestion box.",
            "Or skip the samples and upload a document of your own — I'm not picky about the source, only that it's new to me.",
          ],
          button: onUpload ? undefined : { label: "Go to Upload", onClick: () => router.push(`/n/${noosphereId}/upload`) },
          showSampleIcons: true,
        };
      case "visit_documents":
        return {
          pose: QUEST_POSE.visit_documents!,
          lines: ["Nice — that's ingested. Now go check it out in Documents."],
          button: onDocumentsList ? undefined : { label: "Go to Documents", onClick: () => router.push(`/n/${noosphereId}/documents`) },
        };
      case "open_document":
        return {
          pose: QUEST_POSE.open_document!,
          lines: [
            onDocumentsList
              ? "Click the file you just added to see everything it extracted."
              : "Back in Documents, click the file you just added.",
          ],
          button: onDocumentsList ? undefined : { label: "Go to Documents", onClick: () => router.push(`/n/${noosphereId}/documents`) },
        };
      case "view_orrery":
        return {
          pose: QUEST_POSE.view_orrery!,
          lines: ["Now see it live in the Orrery — every entity you just met, as a star."],
          button: onOrrery ? undefined : { label: "Go to Orrery", onClick: () => router.push(`/n/${noosphereId}/orrery`) },
        };
      case "search":
        return {
          pose: QUEST_POSE.search!,
          lines: [
            onOrrery
              ? "Try the search bar for a keyword from one of the documents you ingested."
              : "Back in Orrery, try the search bar for a keyword from one of the documents you ingested.",
          ],
          button: onOrrery ? undefined : { label: "Go to Orrery", onClick: () => router.push(`/n/${noosphereId}/orrery`) },
        };
      case "simmer":
        return {
          pose: QUEST_POSE.simmer!,
          lines: [
            onPipeline
              ? <>Click <strong>simmer general spec</strong> below to refine extraction.</>
              : <>Head to Pipeline and click <strong>simmer general spec</strong> to refine extraction.</>,
            "Tip: simmering works best with more to learn from — around 20 documents is a good point to start it. You can also just try it now on what you have.",
          ],
          button: onPipeline ? undefined : { label: "Go to Pipeline", onClick: () => router.push(`/n/${noosphereId}/pipeline`) },
        };
      case undefined:
        return {
          pose: IDLE_POSE,
          lines: [
            <>Visit <code>/n/{noosphereId}/tutorial</code> for search, the galaxy map, and building your own domain.</>,
          ],
        };
      default:
        return {
          pose: (activeQuest && QUEST_POSE[activeQuest.id]) ?? IDLE_POSE,
          // Title itself is rendered above these lines (see the bubble's title row), so no
          // need to repeat it here — just a light nudge for quests without dedicated copy yet.
          lines: ["Head there when you're ready."],
        };
    }
  })();

  const cheering = cheerQuestId !== null;
  const displayPose = cheering ? QUEST_POSE[cheerQuestId!] ?? IDLE_POSE : guidance.pose;
  const displayLines: (string | React.ReactNode)[] = cheering
    ? [CHEER_LINE[cheerQuestId!] ?? "Nicely done."]
    : guidance.lines;

  return (
    <div className="fixed bottom-4 left-4 z-50 w-72">
      {!expanded ? (
        <button
          onClick={toggle}
          className="flex items-center gap-2 pl-1 pr-3 py-1 rounded-full border border-border/50 bg-card/90 backdrop-blur hover:bg-accent/40 shadow-lg"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`/mascot/${displayPose}`} alt="" className="w-8 h-auto" />
          <span className="text-xs">Lex · {activeQuest ? activeQuest.title : "All caught up"}</span>
        </button>
      ) : (
        <div className="space-y-2">
          {/* The mascot is always here, guiding or cheering — never absent while expanded. */}
          <div className="flex items-end gap-2" role="status" aria-live="polite">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`/mascot/${displayPose}`}
              alt=""
              className={`w-16 h-auto drop-shadow-lg transition-transform ${cheering ? "scale-105" : ""}`}
            />
            <div
              className={`flex-1 rounded-lg border backdrop-blur px-3 py-2 shadow-lg space-y-1.5 ${
                cheering ? "border-emerald-500/30 bg-card/95" : "border-border/50 bg-card/90"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
                  ✦ Lex
                </span>
                <button onClick={toggle} className="text-[10px] text-muted-foreground hover:text-foreground">
                  minimize
                </button>
              </div>
              {(cheering || introAcknowledged || activeQuest?.id !== "ingest") && (
                <p className={`text-xs font-medium ${cheering ? "text-emerald-400" : "text-foreground"}`}>
                  {cheering
                    ? `${quests.find((q) => q.id === cheerQuestId)?.title} ✓`
                    : activeQuest?.title ?? "All caught up"}
                </p>
              )}
              {displayLines.map((line, i) => (
                <p key={i} className={`text-xs ${i > 0 ? "text-muted-foreground" : ""}`}>
                  {line}
                </p>
              ))}
              {showAddMorePrompt && !cheering && (
                <p className="text-xs text-muted-foreground pt-1 border-t border-border/30">
                  Whenever you&apos;re back, you can always add more files — drag one onto the
                  ingestion box on Upload, or drop your own file into the matching section (or select
                  a folder to upload).
                </p>
              )}
            </div>
          </div>

          {!cheering && (guidance.showSampleIcons || showAddMorePrompt) && (
            <div className="ml-[72px] space-y-2">
              <SampleIcons onUpload={onUpload} ingestedTitles={documentTitles} />
            </div>
          )}

          {!cheering && guidance.button && (
            <div className="ml-[72px]">
              <button
                className="text-xs px-2 py-1 rounded border border-border/40 hover:bg-accent/40 bg-card/90"
                onClick={guidance.button.onClick}
              >
                {guidance.button.label}
              </button>
            </div>
          )}

          <div className="rounded border border-border/50 bg-card/90 backdrop-blur shadow-lg p-3 space-y-2">
            {optionalQuests.length > 0 && (
              <div className="space-y-1">
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

            <div className="space-y-1">
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
        </div>
      )}
    </div>
  );
}
