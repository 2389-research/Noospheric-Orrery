"use client";

import { ENTITY_COLORS } from "./colors";

export interface TooltipEntity {
  id: string;
  canonical_name: string;
  type: string;
  mention_count: number;
  source_count: number;
  snippets: string[];
  is_new: boolean;
}

interface ReaderTooltipProps {
  entity: TooltipEntity | null;
  x: number;
  y: number;
}

export function ReaderTooltip({ entity, x, y }: ReaderTooltipProps) {
  if (!entity) return null;

  const colors = ENTITY_COLORS[entity.type] ?? ENTITY_COLORS["Concept"];

  // Flip left if overflows right
  const flipLeft = typeof window !== "undefined" && x + 250 > window.innerWidth;
  const left = flipLeft ? x - 250 - 14 : x + 14;
  const top = y - 10;

  const snippets = entity.snippets.slice(0, 3);

  return (
    <div
      className="fixed z-50 rounded border border-border/40 bg-card shadow-lg"
      style={{
        left,
        top,
        minWidth: 190,
        maxWidth: 250,
        pointerEvents: "none",
        fontFamily: "var(--font-mono, monospace)",
      }}
    >
      <div className="p-3 space-y-2">
        {/* Name + type badge */}
        <div className="space-y-1">
          <div className="text-[13px] text-foreground/95 font-medium leading-tight">
            {entity.canonical_name}
          </div>
          <span
            className="inline-block text-[8px] tracking-[1px] uppercase px-1.5 py-0.5 rounded font-medium"
            style={{ backgroundColor: colors.bgSolid, color: colors.color }}
          >
            {entity.type}
          </span>
        </div>

        {/* Stats */}
        <div className="space-y-0.5">
          <div className="flex justify-between gap-3 text-[10px]">
            <span className="text-muted-foreground/70">In this doc</span>
            <span className="text-muted-foreground/90">{entity.mention_count} mentions</span>
          </div>
          <div className="flex justify-between gap-3 text-[10px]">
            <span className="text-muted-foreground/70">Across corpus</span>
            <span className="text-muted-foreground/90">{entity.source_count} docs</span>
          </div>
          {entity.is_new && (
            <div className="flex justify-between gap-3 text-[10px]">
              <span className="text-muted-foreground/70">Status</span>
              <span className="text-emerald-400/90">new this batch</span>
            </div>
          )}
        </div>

        {/* Snippets */}
        {snippets.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[9px] tracking-[1px] uppercase text-muted-foreground/70 border-t border-border/20 pt-2">
              Mentions in doc
            </div>
            {snippets.map((snippet, i) => (
              <div
                key={i}
                className="text-[11px] text-muted-foreground/80 bg-background/60 rounded px-2 py-1.5 leading-relaxed border border-border/20"
              >
                {snippet}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
