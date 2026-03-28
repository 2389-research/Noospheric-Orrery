"use client";

import { useState, useCallback, useEffect } from "react";
import { api } from "@/lib/api";
import { EntitySidebar } from "./entity-sidebar";
import { DocumentBody } from "./document-body";
import { ReaderTooltip } from "./reader-tooltip";
import type { TooltipEntity } from "./reader-tooltip";

interface ReaderPaneProps {
  documentId: string;
  onClose: () => void;
}

interface ReaderData {
  document: { id: string; title: string; status: string; domains: string[] };
  entities: {
    id: string;
    canonical_name: string;
    type: string;
    source_count: number;
    mention_count: number;
    positions: number[];
    snippets: string[];
    merge_history: string[];
    is_new: boolean;
  }[];
  segments: {
    type: string;
    text: string;
    entity_id?: string;
    entity_name?: string;
    entity_type?: string;
    is_new?: boolean;
  }[];
  total_mentions: number;
}

interface TooltipState {
  entity: TooltipEntity | null;
  x: number;
  y: number;
}

export function ReaderPane({ documentId, onClose }: ReaderPaneProps) {
  const [data, setData] = useState<ReaderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Reader interaction state
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({ entity: null, x: 0, y: 0 });

  // Active = pinned ?? hovered
  const activeId = pinned ?? hovered ?? null;

  // Fetch reader data
  useEffect(() => {
    setLoading(true);
    setError(null);
    setHovered(null);
    setPinned(null);
    setTooltip({ entity: null, x: 0, y: 0 });

    api.getDocumentReader(documentId)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load document");
        setLoading(false);
      });
  }, [documentId]);

  const handleHoverEntity = useCallback((id: string | null) => {
    setHovered(id);
  }, []);

  const handlePinEntity = useCallback((id: string) => {
    setPinned((prev) => (prev === id ? null : id));
  }, []);

  const handleTooltipMove = useCallback(
    (id: string, x: number, y: number) => {
      if (!data) return;
      const entity = data.entities.find((e) => e.id === id);
      if (!entity) return;
      setTooltip({
        entity: {
          id: entity.id,
          canonical_name: entity.canonical_name,
          type: entity.type,
          mention_count: entity.mention_count,
          source_count: entity.source_count,
          snippets: entity.snippets,
          is_new: entity.is_new,
        },
        x,
        y,
      });
    },
    [data]
  );

  const handleTooltipHide = useCallback(() => {
    setTooltip({ entity: null, x: 0, y: 0 });
  }, []);

  const handleSidebarHover = useCallback((id: string | null) => {
    setHovered(id);
  }, []);

  const handleSidebarPin = useCallback((id: string) => {
    setPinned((prev) => (prev === id ? null : id));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <p className="text-muted-foreground/90 text-xs tracking-[2px] animate-pulse">loading…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center h-48">
        <p className="text-red-400 text-xs">{error ?? "Unknown error"}</p>
      </div>
    );
  }

  const sidebarEntities = data.entities.map((e) => ({
    id: e.id,
    canonical_name: e.canonical_name,
    type: e.type,
    mention_count: e.mention_count,
    is_new: e.is_new,
    positions: e.positions,
  }));

  const activeEntity = activeId ? data.entities.find((e) => e.id === activeId) : null;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Reader header */}
      <div className="flex items-center justify-between px-3 py-2 border border-border/30 rounded mb-3 shrink-0">
        <button
          onClick={onClose}
          className="text-[10px] tracking-[1px] text-muted-foreground/70 hover:text-muted-foreground transition-colors flex items-center gap-1"
        >
          <span>←</span>
          <span>all entities</span>
        </button>
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] text-foreground/90 truncate">{data.document.title}</span>
          {data.document.domains[0] && (
            <span className="text-[9px] text-muted-foreground/60 shrink-0">
              {data.document.domains[0]}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[9px] text-muted-foreground/60">
            {data.total_mentions} mentions
          </span>
          {pinned && (
            <button
              onClick={() => setPinned(null)}
              className="text-[9px] tracking-[0.5px] text-amber-400/80 hover:text-amber-400 transition-colors border border-amber-400/30 rounded px-1.5 py-0.5"
            >
              unpin
            </button>
          )}
        </div>
      </div>

      {/* Reader shell: sidebar + document */}
      <div
        className="flex-1 min-h-0 grid overflow-hidden"
        style={{ gridTemplateColumns: "172px minmax(0, 1fr)", gap: 10 }}
      >
        {/* Entity sidebar */}
        <div className="overflow-y-auto">
          <EntitySidebar
            entities={sidebarEntities}
            activeId={activeId}
            onHover={handleSidebarHover}
            onPin={handleSidebarPin}
            pinnedId={pinned}
          />
        </div>

        {/* Document panel */}
        <div className="border border-border/30 rounded overflow-hidden flex flex-col">
          {/* Document header */}
          <div className="flex items-center justify-between px-4 py-2 border-b border-border/20 shrink-0">
            <span className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase">
              Document
            </span>
            {activeEntity && (
              <span className="text-[10px] text-muted-foreground/70">
                viewing{" "}
                <span className="text-foreground/90">{activeEntity.canonical_name}</span>
                {" "}·{" "}
                {activeEntity.mention_count} in doc
              </span>
            )}
          </div>

          {/* Scrollable document body */}
          <div className="overflow-y-auto flex-1">
            <DocumentBody
              segments={data.segments}
              activeId={activeId}
              onHoverEntity={handleHoverEntity}
              onPinEntity={handlePinEntity}
              onTooltipMove={handleTooltipMove}
              onTooltipHide={handleTooltipHide}
            />
          </div>
        </div>
      </div>

      {/* Tooltip — fixed positioned, outside scroll containers */}
      <ReaderTooltip entity={tooltip.entity} x={tooltip.x} y={tooltip.y} />
    </div>
  );
}
