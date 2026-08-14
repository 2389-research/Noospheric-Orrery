"use client";

// Onboarding tutorial — see docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md
// (including "Revision 1 — UX feedback" for the single-focus stepper, domain list, and
// optimistic ingest updates below). Runs against the real API, scoped to this route's
// sandbox noosphere. Quest state is derived from polling real data, not a separate
// progress table.
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

const SAMPLE_FILES = [
  "entertainment-002.txt",
  "politics-296.txt",
  "sport-056.txt",
];

type QuestId =
  | "ingest"
  | "meet_entities"
  | "classify"
  | "simmer"
  | "normalize"
  | "search"
  | "collection"
  | "star";

interface Quest {
  id: QuestId;
  part: 1 | 2 | 3;
  title: string;
  lore: string;
  done: boolean;
}

function orreryVisitKey(noosphereId: string, step: "collection" | "star") {
  return `tutorial:${noosphereId}:${step}`;
}

export default function TutorialPage() {
  const { noosphereId } = useParams<{ noosphereId: string }>();

  const [documentCount, setDocumentCount] = useState(0);
  const [domains, setDomains] = useState<{ path: string; document_count: number }[]>([]);
  const [entityCount, setEntityCount] = useState(0);
  const [enteredReader, setEnteredReader] = useState(false);
  const [simmerJobId, setSimmerJobId] = useState<string | null>(null);
  const [simmerDone, setSimmerDone] = useState(false);
  const [simmerSkipped, setSimmerSkipped] = useState(false);
  const [normalizeDone, setNormalizeDone] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [collectionVisited, setCollectionVisited] = useState(false);
  const [starVisited, setStarVisited] = useState(false);

  const [loadingSamples, setLoadingSamples] = useState(false);
  const [ingestedSamples, setIngestedSamples] = useState<Set<string>>(new Set());
  const [lastIngested, setLastIngested] = useState<{ title: string; domains: string[]; entity_count: number } | null>(null);
  const [simmerRunning, setSimmerRunning] = useState(false);
  const [normalizing, setNormalizing] = useState(false);
  const [reviewQueue, setReviewQueue] = useState<{ id: string; entity_a: string; entity_b: string }[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{ id: string; name: string; type: string }[] | null>(null);
  const [entities, setEntities] = useState<{ id: string; canonical_name: string; type: string }[]>([]);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [docs, doms, ents] = await Promise.all([
        api.getDocuments(),
        api.getDomains(),
        api.getEntities({ limit: 50 }),
      ]);
      setDocumentCount(docs.length);
      setDomains(doms.map((d) => ({ path: d.path, document_count: d.document_count })));
      setEntityCount(ents.length);
      setEntities(ents.map((e) => ({ id: e.id, canonical_name: e.canonical_name, type: e.type })));
    } catch {
      /* sandbox still spinning up — ignore, next poll retries */
    }
    try {
      const summary = await api.getNormalizationSummary();
      if (summary.total_merges > 0) setNormalizeDone(true);
    } catch {
      /* ignore */
    }
    setCollectionVisited(localStorage.getItem(orreryVisitKey(noosphereId, "collection")) === "1");
    setStarVisited(localStorage.getItem(orreryVisitKey(noosphereId, "star")) === "1");
  }, [noosphereId]);

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  // Poll a running simmer job until it completes.
  useEffect(() => {
    if (!simmerJobId || simmerDone) return;
    const t = setInterval(async () => {
      const job = await api.getJob(simmerJobId);
      if (job?.status === "completed") {
        setSimmerDone(true);
        setSimmerRunning(false);
        clearInterval(t);
      } else if (job?.status === "failed") {
        setSimmerRunning(false);
        clearInterval(t);
      }
    }, 3000);
    return () => clearInterval(t);
  }, [simmerJobId, simmerDone]);

  const ingestSample = async (name: string) => {
    setLoadingSamples(true);
    try {
      const res = await fetch(`/tutorial_samples/${name}`);
      const blob = await res.blob();
      const file = new File([blob], name, { type: "text/plain" });
      const result = await api.ingestFile(file);
      // Apply immediately — don't wait for the next 3s poll tick to show the
      // first ingested document. See spec "Revision 1: immediate ingest feedback".
      setLastIngested({ title: result.title, domains: result.domains, entity_count: result.entity_count });
      setDocumentCount((c) => c + 1);
      setIngestedSamples((s) => new Set(s).add(name));
      await refresh();
    } finally {
      setLoadingSamples(false);
    }
  };

  const loadSampleDocs = async () => {
    for (const name of SAMPLE_FILES) {
      if (!ingestedSamples.has(name)) await ingestSample(name);
    }
  };

  const onDropSample = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const name = e.dataTransfer.getData("text/tutorial-sample");
    if (name && !ingestedSamples.has(name) && !loadingSamples) ingestSample(name);
  };

  const runSimmer = async () => {
    setSimmerRunning(true);
    const { job_id } = await api.triggerGeneralSimmer();
    setSimmerJobId(job_id);
  };

  const skipSimmer = () => setSimmerSkipped(true);

  const runNormalize = async () => {
    setNormalizing(true);
    try {
      const result = await api.triggerNormalization();
      if (result.queued_for_review > 0) {
        const queue = await api.getReviewQueue();
        setReviewQueue(queue);
      }
      if (result.plural_merges + result.embedding_merges > 0) setNormalizeDone(true);
    } finally {
      setNormalizing(false);
    }
  };

  const resolveOne = async (id: string, action: "merge" | "keep_separate") => {
    await api.resolveReview(id, action);
    setReviewQueue((q) => q.filter((r) => r.id !== id));
    setNormalizeDone(true);
  };

  const runSearch = async () => {
    if (!searchQuery.trim()) return;
    const result = await api.search(searchQuery);
    setSearchResults(result.entities);
    setSearchDone(true);
  };

  const markVisited = (step: "collection" | "star") => {
    localStorage.setItem(orreryVisitKey(noosphereId, step), "1");
    if (step === "collection") setCollectionVisited(true);
    if (step === "star") setStarVisited(true);
  };

  const quests: Quest[] = [
    {
      id: "ingest",
      part: 1,
      title: "Ingest a document",
      lore: "A star ignites in the dark — your Orrery has its first light.",
      done: documentCount > 0,
    },
    {
      id: "meet_entities",
      part: 1,
      title: "Meet your entities",
      lore: "Names resolve into nodes. The graph begins to remember.",
      done: enteredReader || entityCount > 0,
    },
    {
      id: "classify",
      part: 1,
      title: "Watch it classify",
      lore: "Constellations form where none were named before.",
      done: domains.length >= 2,
    },
    {
      id: "simmer",
      part: 1,
      title: "Run a simmer",
      lore: simmerSkipped
        ? "Skipped for now — the spec stays general until you come back to this."
        : "The spec has been refined. Extraction quality just improved.",
      done: simmerDone || simmerSkipped,
    },
    {
      id: "normalize",
      part: 1,
      title: "Normalize",
      lore: "Duplicate stars merge into one.",
      done: normalizeDone,
    },
    {
      id: "search",
      part: 2,
      title: "Search",
      lore: "The graph knows what you were looking for.",
      done: searchDone,
    },
    {
      id: "collection",
      part: 2,
      title: "Descend into a collection",
      lore: "One layer down — the galaxy resolves into a dataset.",
      done: collectionVisited,
    },
    {
      id: "star",
      part: 2,
      title: "Zoom to a star",
      lore: "A single entity, traced back to its source.",
      done: starVisited,
    },
  ];

  const activeIndex = quests.findIndex((q) => !q.done);
  const activeQuest = activeIndex === -1 ? null : quests[activeIndex];
  const done = (id: QuestId) => quests.find((q) => q.id === id)?.done ?? false;

  return (
    <div className="grid grid-cols-[1fr_320px] gap-6">
      <div className="space-y-6">
        <header className="space-y-1">
          <h1 className="text-lg font-semibold tracking-wide">Calibrating Your Orrery</h1>
          <p className="text-xs text-muted-foreground">
            Sandbox noosphere · resets every time you re-enter this tutorial
          </p>
        </header>

        {/* Active quest — one card at a time */}
        {activeQuest?.id === "ingest" && (
          <QuestCard title="Part 1 — Ingest a document">
            <p className="text-sm">Drag a sample article into the sandbox to ingest it.</p>

            <div className="flex gap-3">
              {SAMPLE_FILES.map((name) => {
                const category = name.split("-")[0];
                const done = ingestedSamples.has(name);
                return (
                  <div
                    key={name}
                    draggable={!done}
                    onDragStart={(e) => e.dataTransfer.setData("text/tutorial-sample", name)}
                    onClick={() => !done && !loadingSamples && ingestSample(name)}
                    className={`flex flex-col items-center gap-1 w-20 p-2 rounded border cursor-grab select-none ${
                      done ? "border-border/20 opacity-40 cursor-default" : "border-border/50 hover:bg-accent/40"
                    }`}
                    title={done ? `${name} — already ingested` : `Drag or click to ingest ${name}`}
                  >
                    <span className="text-2xl">📄</span>
                    <span className="text-[10px] text-center text-muted-foreground truncate w-full">{category}</span>
                  </div>
                );
              })}
            </div>

            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={onDropSample}
              className="rounded border-2 border-dashed border-border/40 p-4 text-center text-xs text-muted-foreground"
            >
              {loadingSamples ? "Ingesting..." : "Drop here to ingest"}
            </div>

            <button
              className="text-xs px-3 py-1.5 rounded border border-border/30 text-muted-foreground hover:text-foreground disabled:opacity-40"
              disabled={loadingSamples || SAMPLE_FILES.every((n) => ingestedSamples.has(n))}
              onClick={loadSampleDocs}
            >
              {loadingSamples ? "Loading..." : "Or load all at once"}
            </button>
            <p className="text-xs text-muted-foreground">
              Prefer your own content? Head to{" "}
              <Link href={`/n/${noosphereId}/upload`} className="underline">
                Upload
              </Link>{" "}
              and drop in a document of your own instead.
            </p>

            {lastIngested && (
              <div className="text-xs text-muted-foreground pt-2 border-t border-border/30 space-y-1">
                <p>
                  Just ingested <span className="text-foreground">{lastIngested.title}</span> —{" "}
                  {lastIngested.entity_count} entities.
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {lastIngested.domains.map((d) => (
                    <span key={d} className="text-[11px] px-2 py-0.5 rounded-full border border-border/40">
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </QuestCard>
        )}

        {activeQuest?.id === "meet_entities" && (
          <QuestCard title="Part 1 — Meet your entities">
            <p className="text-sm">Click an entity below to open it.</p>
            <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
              {entities.slice(0, 24).map((e) => (
                <button
                  key={e.id}
                  className="text-[11px] px-2 py-0.5 rounded-full border border-border/40 text-muted-foreground hover:text-foreground"
                  onClick={() => setEnteredReader(true)}
                  title={e.type}
                >
                  {e.canonical_name}
                </button>
              ))}
              {entities.length === 0 && <span className="text-xs text-muted-foreground">Waiting for extraction...</span>}
            </div>
          </QuestCard>
        )}

        {activeQuest?.id === "classify" && (
          <QuestCard title="Part 1 — Watch it classify">
            <p className="text-xs text-muted-foreground">
              None of these article topics match an existing top-level domain exactly, so the
              classifier invents new topics for them — the taxonomy is open-vocabulary, not a fixed
              list.
            </p>
            <div className="space-y-1">
              {domains.map((d) => (
                <div key={d.path} className="flex items-center justify-between text-xs">
                  <span className="font-mono">{d.path}</span>
                  <span className="text-muted-foreground">{d.document_count} doc(s)</span>
                </div>
              ))}
              {domains.length === 0 && <span className="text-xs text-muted-foreground">Waiting for classification...</span>}
            </div>
          </QuestCard>
        )}

        {activeQuest?.id === "simmer" && (
          <QuestCard title="Part 1 — Run a simmer">
            <p className="text-sm">Refine the extraction spec against your sandbox&apos;s documents.</p>
            <p className="text-xs text-muted-foreground">
              Tip: simmering works best with more to learn from — around 20 documents is a good
              point to start it. Click the button below to try it now on what you have.
            </p>
            <div className="flex gap-2">
              <button
                className="text-xs px-3 py-1.5 rounded border border-border/50 hover:bg-accent/40 disabled:opacity-40"
                disabled={simmerRunning}
                onClick={runSimmer}
              >
                {simmerRunning ? "Simmering... (can take a few minutes)" : "Run simmer"}
              </button>
              <button
                className="text-xs px-3 py-1.5 rounded border border-border/30 text-muted-foreground hover:text-foreground disabled:opacity-40"
                disabled={simmerRunning}
                onClick={skipSimmer}
              >
                Skip for now
              </button>
            </div>
          </QuestCard>
        )}

        {activeQuest?.id === "normalize" && (
          <QuestCard title="Part 1 — Normalize">
            <p className="text-sm">Merge duplicate entities.</p>
            <button
              className="text-xs px-3 py-1.5 rounded border border-border/50 hover:bg-accent/40 disabled:opacity-40"
              disabled={normalizing}
              onClick={runNormalize}
            >
              {normalizing ? "Normalizing..." : "Run normalize"}
            </button>
            {reviewQueue.length > 0 && (
              <div className="space-y-2 pt-2 border-t border-border/30">
                <p className="text-xs text-muted-foreground">Review queue:</p>
                {reviewQueue.map((r) => (
                  <div key={r.id} className="flex items-center gap-2 text-xs">
                    <span>{r.entity_a} ↔ {r.entity_b}</span>
                    <button className="px-2 py-0.5 rounded border border-border/40" onClick={() => resolveOne(r.id, "merge")}>Merge</button>
                    <button className="px-2 py-0.5 rounded border border-border/40" onClick={() => resolveOne(r.id, "keep_separate")}>Keep separate</button>
                  </div>
                ))}
              </div>
            )}
          </QuestCard>
        )}

        {activeQuest?.id === "search" && (
          <QuestCard title="Part 2 — Search">
            <p className="text-sm">Search your sandbox graph.</p>
            <div className="flex gap-2">
              <input
                className="flex-1 text-xs bg-transparent border border-border/50 rounded px-2 py-1"
                placeholder="e.g. profit, election, match"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
              />
              <button className="text-xs px-3 py-1.5 rounded border border-border/50 hover:bg-accent/40" onClick={runSearch}>
                Search
              </button>
            </div>
            {searchResults && (
              <div className="flex flex-wrap gap-1.5">
                {searchResults.map((r) => (
                  <span key={r.id} className="text-[11px] px-2 py-0.5 rounded-full border border-border/40 text-muted-foreground">
                    {r.name}
                  </span>
                ))}
                {searchResults.length === 0 && <span className="text-xs text-muted-foreground">No results yet.</span>}
              </div>
            )}
          </QuestCard>
        )}

        {(activeQuest?.id === "collection" || activeQuest?.id === "star") && (
          <QuestCard title={`Part 2 — ${activeQuest.id === "collection" ? "Descend into a collection" : "Zoom to a star"}`}>
            <p className="text-sm">Open the Orrery and drill down: galaxy → collection → star.</p>
            <div className="flex gap-2">
              <Link
                href={`/n/${noosphereId}/orrery`}
                className="text-xs px-3 py-1.5 rounded border border-border/50 hover:bg-accent/40"
                onClick={() => markVisited(activeQuest.id as "collection" | "star")}
              >
                Open Orrery
              </Link>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Simplification for this first pass: marked done as soon as you open the Orrery; a later
              pass should detect the actual viewMode transition instead.
            </p>
          </QuestCard>
        )}

        {/* Part 3 — unlocks once everything above is done */}
        {activeQuest === null && (
          <div className="space-y-4">
            <QuestCard title="Part 3 — Reflect on your Orrery">
              <p className="text-xs text-muted-foreground">
                You found {entityCount} entities across {domains.length} domains from {documentCount} documents.
                Notice what felt generic, and what an invented topic reveals about the taxonomy&apos;s
                open-endedness. (Fallback prebuilt graph for skipped ingestion: not yet implemented.)
              </p>
            </QuestCard>
            <QuestCard title="Part 3 — Get the skill">
              <p className="text-sm">
                Open a Claude Code session in this repo and say something like:
              </p>
              <pre className="text-xs bg-black/30 rounded p-3 whitespace-pre-wrap">
                &quot;I want to build my own version of this for [your domain] — use the
                design-your-orrery skill.&quot;
              </pre>
              <p className="text-xs text-muted-foreground">
                It walks through planning a custom domain spec for your own Orrery, using{" "}
                <code>orchestrator/specs/research_paper/</code> (on{" "}
                <code>feature/research-paper-section-spec</code>) as a worked example. Defined at{" "}
                <code>.claude/skills/design-your-orrery/SKILL.md</code>.
              </p>
            </QuestCard>
          </div>
        )}
      </div>

      {/* Quest log + live thumbnail */}
      <aside className="space-y-4">
        <div className="rounded border border-border/50 overflow-hidden bg-black/40" style={{ height: 150 }}>
          <iframe
            title="sandbox orrery thumbnail"
            src={`/viz/index.html?api=${encodeURIComponent("/api")}&token=noop&workspace=${encodeURIComponent(noosphereId)}`}
            style={{ width: "100%", height: "100%", border: "none", pointerEvents: "none" }}
          />
        </div>
        <div className="rounded border border-border/50 p-3 space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Quest Log</p>
          {quests.map((q) => (
            <div
              key={q.id}
              className={`flex items-start gap-2 text-xs ${q.id === activeQuest?.id ? "opacity-100" : q.done ? "opacity-100" : "opacity-40"}`}
            >
              <span className={done(q.id) ? "text-emerald-400" : q.id === activeQuest?.id ? "text-amber-400" : "text-muted-foreground/50"}>
                {done(q.id) ? "✓" : q.id === activeQuest?.id ? "●" : "○"}
              </span>
              <div>
                <div className={done(q.id) || q.id === activeQuest?.id ? "text-foreground" : "text-muted-foreground"}>{q.title}</div>
                {q.done && <div className="text-[10px] text-muted-foreground/70 italic">{q.lore}</div>}
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

function QuestCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded border border-border/50 p-5">
      <h2 className="text-xs uppercase tracking-widest text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}
