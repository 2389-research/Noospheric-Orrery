"use client";

// Shared quest-state polling, used by both the standalone /tutorial page and the
// persistent TutorialPanel. See docs/superpowers/specs/2026-08-10-onboarding-tutorial-design.md
// ("Revision 2 — persistent cross-page panel").
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export type QuestId =
  | "ingest"
  | "visit_documents"
  | "meet_entities"
  | "classify"
  | "simmer"
  | "normalize";

export interface Quest {
  id: QuestId;
  title: string;
  lore: string;
  done: boolean;
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
  const [enteredReader, setEnteredReader] = useState(false);
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
      id: "meet_entities",
      title: "Meet your entities",
      lore: "Names resolve into nodes. The graph begins to remember.",
      done: enteredReader || entityCount > 0,
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
    setEnteredReader,
    simmerDone,
    setSimmerDone,
    simmerSkipped,
    setSimmerSkipped,
    normalizeDone,
    setNormalizeDone,
  };
}
