"use client";

import { ENTITY_COLORS, TYPE_ORDER } from "./colors";

export interface SidebarEntity {
  id: string;
  canonical_name: string;
  type: string;
  mention_count: number;
  is_new: boolean;
  positions: number[];
}

interface EntitySidebarProps {
  entities: SidebarEntity[];
  activeId: string | null;
  onHover: (id: string | null) => void;
  onPin: (id: string) => void;
  pinnedId: string | null;
  onNavigate?: (id: string) => void;
}

function OccurrenceMinimap({
  positions,
  color,
  isActive,
}: {
  positions: number[];
  color: string;
  isActive: boolean;
}) {
  return (
    <div
      className="relative shrink-0 rounded-sm border border-border/20"
      style={{ width: 24, height: 36 }}
    >
      {positions.map((pos, i) => (
        <div
          key={i}
          className="absolute left-[2px] right-[2px] transition-opacity"
          style={{
            top: Math.round(pos * 32),
            height: 2,
            backgroundColor: color,
            opacity: isActive ? 1.0 : 0.45,
          }}
        />
      ))}
    </div>
  );
}

interface SidebarRowProps {
  entity: SidebarEntity;
  isActive: boolean;
  onHover: (id: string | null) => void;
  onPin: (id: string) => void;
  pinnedId: string | null;
  onNavigate?: (id: string) => void;
}

function SidebarRow({ entity, isActive, onHover, onPin, pinnedId, onNavigate }: SidebarRowProps) {
  const colors = ENTITY_COLORS[entity.type] ?? ENTITY_COLORS["Concept"];

  return (
    <button
      className="w-full text-left flex items-center gap-2 transition-colors hover:bg-card/30 focus:outline-none"
      style={{
        padding: "5px 10px",
        borderLeft: isActive ? `2px solid ${colors.color}` : "2px solid transparent",
      }}
      onMouseEnter={() => onHover(entity.id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onPin(entity.id)}
      onDoubleClick={() => onNavigate?.(entity.id)}
      title={`${entity.canonical_name} — double-click to view star graph`}
    >
      {/* Name + badge */}
      <div className="flex-1 min-w-0 flex items-center gap-1.5">
        <span className="text-[11px] text-foreground/90 truncate leading-tight">
          {entity.canonical_name}
        </span>
        {entity.is_new && (
          <span className="shrink-0 text-[7px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400 uppercase tracking-[0.5px] font-medium">
            new
          </span>
        )}
      </div>

      {/* Minimap */}
      <OccurrenceMinimap
        positions={entity.positions}
        color={colors.color}
        isActive={isActive}
      />
    </button>
  );
}

export function EntitySidebar({
  entities,
  activeId,
  onHover,
  onPin,
  pinnedId,
  onNavigate,
}: EntitySidebarProps) {
  // Group entities by type in fixed order
  const grouped: { type: string; entities: SidebarEntity[] }[] = TYPE_ORDER.map((type) => ({
    type,
    entities: entities
      .filter((e) => e.type === type)
      .sort((a, b) => b.mention_count - a.mention_count),
  })).filter((g) => g.entities.length > 0);

  // Also include any types not in TYPE_ORDER
  const knownTypes = new Set(TYPE_ORDER as readonly string[]);
  const extraTypes = [...new Set(entities.map((e) => e.type).filter((t) => !knownTypes.has(t)))];
  extraTypes.forEach((type) => {
    grouped.push({
      type,
      entities: entities
        .filter((e) => e.type === type)
        .sort((a, b) => b.mention_count - a.mention_count),
    });
  });

  return (
    <div
      className="border border-border/30 rounded overflow-hidden flex flex-col"
      style={{ width: 172 }}
    >
      <div className="px-2.5 py-2 border-b border-border/20 shrink-0">
        <span className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase">
          Entities
        </span>
      </div>

      <div className="overflow-y-auto flex-1">
        {grouped.map(({ type, entities: groupEntities }) => {
          const colors = ENTITY_COLORS[type] ?? ENTITY_COLORS["Concept"];
          return (
            <div key={type}>
              <div
                className="text-[9px] tracking-[1px] uppercase font-medium"
                style={{ padding: "5px 10px 2px", color: colors.color }}
              >
                {type}
              </div>
              {groupEntities.map((entity) => (
                <SidebarRow
                  key={entity.id}
                  entity={entity}
                  isActive={activeId === entity.id}
                  onHover={onHover}
                  onPin={onPin}
                  pinnedId={pinnedId}
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
