"use client";

import { useEffect, useRef, useCallback } from "react";
import { ENTITY_COLORS } from "./colors";

export interface Segment {
  type: string;
  text: string;
  entity_id?: string;
  entity_name?: string;
  entity_type?: string;
  is_new?: boolean;
}

interface DocumentBodyProps {
  segments: Segment[];
  activeId: string | null;
  onHoverEntity: (id: string | null) => void;
  onPinEntity: (id: string) => void;
  onTooltipMove: (id: string, x: number, y: number) => void;
  onTooltipHide: () => void;
}

function getHighlightStyles(
  entityType: string,
  state: "default" | "lit" | "dim"
): React.CSSProperties {
  const colors = ENTITY_COLORS[entityType] ?? ENTITY_COLORS["Concept"];

  if (state === "dim") {
    return {
      background: "transparent",
      color: "inherit",
      borderBottom: "1.5px solid transparent",
      cursor: "pointer",
    };
  }

  const base: React.CSSProperties = {
    background: colors.bg,
    color: colors.color,
    borderBottom: `1.5px solid ${colors.color}`,
    cursor: "pointer",
    borderRadius: "2px",
    padding: "0 1px",
  };

  if (state === "lit") {
    return { ...base, filter: "brightness(1.15)" };
  }

  return base;
}

export function DocumentBody({
  segments,
  activeId,
  onHoverEntity,
  onPinEntity,
  onTooltipMove,
  onTooltipHide,
}: DocumentBodyProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Update highlight states via DOM manipulation for performance
  const updateHighlights = useCallback(
    (currentActiveId: string | null) => {
      if (!containerRef.current) return;
      const spans = containerRef.current.querySelectorAll<HTMLElement>(".hl");
      spans.forEach((el) => {
        const eid = el.dataset.eid;
        const entityType = el.dataset.etype ?? "Concept";
        const state: "default" | "lit" | "dim" = !currentActiveId
          ? "default"
          : eid === currentActiveId
          ? "lit"
          : "dim";

        el.className = `hl hl-${state}`;
        const styles = getHighlightStyles(entityType, state);
        Object.assign(el.style, {
          background: styles.background ?? "",
          color: styles.color ?? "",
          borderBottom: styles.borderBottom ?? "",
          filter: styles.filter ?? "",
          cursor: styles.cursor ?? "",
          borderRadius: styles.borderRadius ?? "",
          padding: styles.padding ?? "",
        });
      });
    },
    []
  );

  useEffect(() => {
    updateHighlights(activeId);
  }, [activeId, updateHighlights]);

  return (
    <div
      ref={containerRef}
      className="doc-body"
      style={{
        fontSize: 13,
        lineHeight: 2.2,
        padding: "18px 20px",
        fontFamily: "var(--font-mono, monospace)",
      }}
    >
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          // Convert newlines to <br>
          const parts = seg.text.split("\n");
          return (
            <span key={i}>
              {parts.map((part, j) => (
                <span key={j}>
                  {part}
                  {j < parts.length - 1 && <br />}
                </span>
              ))}
            </span>
          );
        }

        if (seg.type === "entity" && seg.entity_id) {
          const entityType = seg.entity_type ?? "Concept";
          const colors = ENTITY_COLORS[entityType] ?? ENTITY_COLORS["Concept"];
          const state: "default" | "lit" | "dim" = !activeId
            ? "default"
            : seg.entity_id === activeId
            ? "lit"
            : "dim";
          const styles = getHighlightStyles(entityType, state);

          return (
            <span
              key={i}
              className={`hl hl-${state}`}
              data-eid={seg.entity_id}
              data-etype={entityType}
              style={{
                background: styles.background,
                color: styles.color,
                borderBottom: styles.borderBottom,
                filter: (styles as { filter?: string }).filter ?? undefined,
                cursor: styles.cursor,
                borderRadius: styles.borderRadius,
                padding: styles.padding,
              }}
              onMouseEnter={(e) => {
                onHoverEntity(seg.entity_id!);
                onTooltipMove(seg.entity_id!, e.clientX, e.clientY);
              }}
              onMouseMove={(e) => {
                onTooltipMove(seg.entity_id!, e.clientX, e.clientY);
              }}
              onMouseLeave={() => {
                onHoverEntity(null);
                onTooltipHide();
              }}
              onClick={() => {
                onPinEntity(seg.entity_id!);
              }}
            >
              {seg.text}
            </span>
          );
        }

        return <span key={i}>{seg.text}</span>;
      })}
    </div>
  );
}
