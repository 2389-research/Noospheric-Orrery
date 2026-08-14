"use client";

// Shared quest-state polling, used by both the standalone /tutorial page and the
// persistent TutorialPanel. See docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md
// ("Revision 2 — persistent cross-page panel", "Revision 3 — Documents → Orrery handoff").
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export type QuestId =
  | "ingest"
  | "visit_documents"
  | "open_document"
  | "view_orrery"
  | "search"
  | "classify"
  | "simmer"
  | "normalize"
  | "add_more_files";

export interface Quest {
  id: QuestId;
  title: string;
  lore: string;
  done: boolean;
  /** Optional quests are shown alongside the active required quest but never
   *  block progression and are never picked as the active quest themselves. */
  optional?: boolean;
}

function key(noosphereId: string, name: string) {
  return `tutorial:${noosphereId}:${name}`;
}

/** Whether this workspace was entered via the /tutorial flow — same flag TutorialPanel
 *  checks before rendering. Real (non-tutorial) pages that want to report a tutorial
 *  action (e.g. "the user just searched") should check this first, so a real user's
 *  real search doesn't write tutorial state that nothing ever reads. */
export function isTutorialActive(noosphereId: string): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(key(noosphereId, "enabled")) === "1";
}

/** Called from the real Orrery page's search handler on a successful search —
 *  not a hook, so pages that don't otherwise use useTutorialQuests can still report this. */
export function markSearched(noosphereId: string): void {
  if (!isTutorialActive(noosphereId)) return;
  localStorage.setItem(key(noosphereId, "searched"), "1");
}

export function useTutorialQuests(noosphereId: string) {
  const [documentCount, setDocumentCount] = useState(0);
  const [documentTitles, setDocumentTitles] = useState<string[]>([]);
  const [domains, setDomains] = useState<{ path: string; document_count: number }[]>([]);
  const [entityCount, setEntityCount] = useState(0);
  const [normalizeDone, setNormalizeDone] = useState(false);
  const [visitedDocuments, setVisitedDocuments] = useState(false);
  const [openedDocument, setOpenedDocument] = useState(false);
  const [visitedOrrery, setVisitedOrrery] = useState(false);
  const [searched, setSearched] = useState(false);
  const [simmerDone, setSimmerDone] = useState(false);
  const [simmerSkipped, setSimmerSkipped] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [docs, doms, ents] = await Promise.all([
        api.getDocuments(),
        api.getDomains(),
        api.getEntities({ limit: 50 }),
      ]);
      setDocumentCount(docs.length);
      setDocumentTitles(docs.map((d) => d.title));
      setDomains(doms.map((d) => ({ path: d.path, document_count: d.document_count })));
      setEntityCount(ents.length);
    } catch {
      /* sandbox still spinning up — ignore, next poll retries */
    }
    try {
      const summary = await api.getNormalizationSummary();
      if (summary.total_merges > 0) setNormalizeDone(true);
    } catch {
      /* ignore */
    }
    setVisitedDocuments(localStorage.getItem(key(noosphereId, "visited_documents")) === "1");
    setOpenedDocument(localStorage.getItem(key(noosphereId, "opened_document")) === "1");
    setVisitedOrrery(localStorage.getItem(key(noosphereId, "visited_orrery")) === "1");
    setSearched(localStorage.getItem(key(noosphereId, "searched")) === "1");
  }, [noosphereId]);

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  const markVisitedDocuments = useCallback(() => {
    localStorage.setItem(key(noosphereId, "visited_documents"), "1");
    setVisitedDocuments(true);
  }, [noosphereId]);

  const markOpenedDocument = useCallback(() => {
    localStorage.setItem(key(noosphereId, "opened_document"), "1");
    setOpenedDocument(true);
  }, [noosphereId]);

  const markVisitedOrrery = useCallback(() => {
    localStorage.setItem(key(noosphereId, "visited_orrery"), "1");
    setVisitedOrrery(true);
  }, [noosphereId]);

  const quests: Quest[] = [
    {
      id: "ingest",
      title: "Ingest a document",
      lore: "A star ignites in the dark — your Orrery has its first light.",
      done: documentCount > 0,
    },
    {
      id: "visit_documents",
      title: "See it in Documents",
      lore: "Your first upload, filed and findable.",
      done: visitedDocuments,
    },
    {
      id: "open_document",
      title: "Click the file you just added",
      lore: "Every extracted name, traced back to the sentence it came from.",
      done: openedDocument,
    },
    {
      id: "view_orrery",
      title: "See the live view in Orrery",
      lore: "The galaxy map, watching itself grow.",
      done: visitedOrrery,
    },
    {
      id: "search",
      title: "Search for a keyword",
      lore: "A query lights up exactly what it touches.",
      done: searched,
    },
    {
      id: "add_more_files",
      title: "Add more files",
      lore: "More sources, more constellations.",
      // Deliberately never "done" — this is a standing invitation, not a one-time checkbox.
      // Whenever the user comes back, more files are still worth adding. See design spec
      // "Revision 8": the previous documentCount > 1 threshold made this disappear after the
      // second file, which is the opposite of what an always-available option should do.
      done: false,
      optional: true,
    },
    {
      id: "classify",
      title: "Watch it classify",
      lore: "Constellations form where none were named before.",
      done: domains.length >= 2,
    },
    {
      id: "simmer",
      title: "Run a simmer",
      lore: simmerSkipped
        ? "Skipped for now — the spec stays general until you come back to this."
        : "The spec has been refined. Extraction quality just improved.",
      done: simmerDone || simmerSkipped,
    },
    {
      id: "normalize",
      title: "Normalize",
      lore: "Duplicate stars merge into one.",
      done: normalizeDone,
    },
  ];

  return {
    quests,
    documentCount,
    documentTitles,
    domains,
    entityCount,
    refresh,
    markVisitedDocuments,
    markOpenedDocument,
    markVisitedOrrery,
    simmerDone,
    setSimmerDone,
    simmerSkipped,
    setSimmerSkipped,
    normalizeDone,
    setNormalizeDone,
  };
}
