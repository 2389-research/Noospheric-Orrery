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

export function useTutorialQuests(noosphereId: string) {
  const [documentCount, setDocumentCount] = useState(0);
  const [domains, setDomains] = useState<{ path: string; document_count: number }[]>([]);
  const [entityCount, setEntityCount] = useState(0);
  const [normalizeDone, setNormalizeDone] = useState(false);
  const [visitedDocuments, setVisitedDocuments] = useState(false);
  const [openedDocument, setOpenedDocument] = useState(false);
  const [visitedOrrery, setVisitedOrrery] = useState(false);
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
      id: "add_more_files",
      title: "Add more files",
      lore: "More sources, more constellations.",
      done: documentCount > 1,
      optional: true,
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
