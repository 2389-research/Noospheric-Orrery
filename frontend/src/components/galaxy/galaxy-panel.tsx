"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { NavTrail, TrailItem } from "./nav-trail";
import { EntityPanelContent, EntityPanelData } from "./entity-panel-content";
import { DomainPanelContent, DomainPanelData } from "./domain-panel-content";
import { TradeRoutePanelContent, TradeRoutePanelData } from "./trade-route-panel-content";

type PanelNode =
  | { nodeType: "entity"; data: EntityPanelData }
  | { nodeType: "domain"; data: DomainPanelData }
  | { nodeType: "trade_route"; data: TradeRoutePanelData };

interface SelectedNodeRaw {
  nodeType: string;
  data: Record<string, unknown>;
}

interface GalaxyPanelProps {
  selectedNode: SelectedNodeRaw | null;
  domainColors: Record<string, string>;
  onClose?: () => void;
}

function parseSelectedNode(selectedNode: SelectedNodeRaw | null): PanelNode | null {
  if (!selectedNode) return null;
  if (selectedNode.nodeType === "entity") {
    const d = selectedNode.data as {
      id?: string;
      name?: string;
      type?: string;
      source_count?: number;
      domain_weights?: Record<string, number>;
      snippets?: string[];
    };
    return {
      nodeType: "entity",
      data: {
        id: String(d.id ?? ""),
        name: String(d.name ?? ""),
        type: String(d.type ?? "Concept"),
        source_count: Number(d.source_count ?? 0),
        domain_weights: d.domain_weights,
        snippets: d.snippets,
      },
    };
  }
  if (selectedNode.nodeType === "domain") {
    const d = selectedNode.data as {
      path?: string;
      name?: string;
      document_count?: number;
    };
    const path = String(d.path ?? "");
    const name = d.name ? String(d.name) : (path.split("/").pop() ?? path);
    return {
      nodeType: "domain",
      data: {
        path,
        name,
        document_count: Number(d.document_count ?? 0),
      },
    };
  }
  if (selectedNode.nodeType === "trade_route") {
    const d = selectedNode.data as {
      source?: string; target?: string;
      sourceLabel?: string; targetLabel?: string;
      weight?: number;
    };
    return {
      nodeType: "trade_route",
      data: {
        source: String(d.source ?? ""),
        target: String(d.target ?? ""),
        sourceLabel: String(d.sourceLabel ?? ""),
        targetLabel: String(d.targetLabel ?? ""),
        weight: Number(d.weight ?? 0),
      },
    };
  }
  return null;
}

export function GalaxyPanel({ selectedNode, domainColors, onClose }: GalaxyPanelProps) {
  // Internal navigation stack: [root, ...navigated]
  const [navStack, setNavStack] = useState<PanelNode[]>([]);
  const prevSelectedNodeRef = useRef<SelectedNodeRaw | null>(null);

  // Reset nav stack when external selectedNode changes
  useEffect(() => {
    if (selectedNode !== prevSelectedNodeRef.current) {
      prevSelectedNodeRef.current = selectedNode;
      const parsed = parseSelectedNode(selectedNode);
      setNavStack(parsed ? [parsed] : []);
    }
  }, [selectedNode]);

  const currentNode = navStack[navStack.length - 1] ?? null;

  // Trail = all items in navStack (last is current)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const trail: TrailItem[] = navStack.map((node: any) => {
    if (node.nodeType === "entity") {
      return { name: node.data.name, nodeType: "entity" as const, id: node.data.id };
    }
    if (node.nodeType === "trade_route") {
      return { name: `${node.data.sourceLabel?.split("/").pop()} ↔ ${node.data.targetLabel?.split("/").pop()}`, nodeType: "trade_route" as const, id: `${node.data.source}:${node.data.target}` };
    }
    return { name: node.data.path?.split("/").pop() ?? node.data.name, nodeType: "domain" as const, id: node.data.path };
  });

  const handleNavigateEntity = useCallback(
    (entity: { id: string; name: string; type: string; source_count: number }) => {
      const node: PanelNode = {
        nodeType: "entity",
        data: {
          id: entity.id,
          name: entity.name,
          type: entity.type,
          source_count: entity.source_count,
        },
      };
      setNavStack((prev) => {
        const next = [...prev, node];
        // Keep max 3 trail items visible by limiting stack to 4 (3 trail + 1 current)
        return next.slice(-4);
      });
    },
    []
  );

  const handleNavigateDomain = useCallback(
    (domainPath: string, domainName: string) => {
      const node: PanelNode = {
        nodeType: "domain",
        data: {
          path: domainPath,
          name: domainName,
          document_count: 0,
        },
      };
      setNavStack((prev) => {
        const next = [...prev, node];
        return next.slice(-4);
      });
    },
    []
  );

  const handleTrailNavigate = useCallback((item: TrailItem, index: number) => {
    // Navigate back to item at index — truncate stack to index+1
    setNavStack((prev) => prev.slice(0, index + 1));
  }, []);

  if (!selectedNode) return null;

  return (
    <div
      style={{
        width: 300,
        flexShrink: 0,
        background: "rgba(6, 13, 34, 0.97)",
        borderRight: "1px solid rgba(100,180,255,0.12)",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        fontFamily: "'Courier New', monospace",
        position: "relative",
      }}
    >
      {/* Close button */}
      <button
        onClick={onClose}
        style={{
          position: "absolute",
          top: 10,
          right: 12,
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "rgba(100,180,255,0.35)",
          fontSize: 14,
          lineHeight: 1,
          padding: 2,
          fontFamily: "'Courier New', monospace",
          zIndex: 1,
        }}
        title="Close panel"
      >
        ✕
      </button>

      {/* NavTrail — show breadcrumbs when there are 2+ items in stack */}
      <NavTrail trail={trail} onNavigate={handleTrailNavigate} />

      {/* Scrollable panel body */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          scrollbarWidth: "thin",
          scrollbarColor: "rgba(100,180,255,0.2) transparent",
        }}
      >
        {currentNode?.nodeType === "entity" && (
          <EntityPanelContent
            data={currentNode.data}
            domainColors={domainColors}
            onNavigateDomain={handleNavigateDomain}
            onNavigateEntity={handleNavigateEntity}
          />
        )}
        {currentNode?.nodeType === "domain" && (
          <DomainPanelContent
            data={currentNode.data}
            domainColor={domainColors[currentNode.data.path]}
            onNavigateEntity={handleNavigateEntity}
            onNavigateDomain={handleNavigateDomain}
          />
        )}
        {currentNode?.nodeType === "trade_route" && (
          <TradeRoutePanelContent
            data={currentNode.data}
            onNavigateDomain={handleNavigateDomain}
            onNavigateEntity={handleNavigateEntity}
          />
        )}
        {!currentNode && (
          <div style={{ padding: 20, fontSize: 11, color: "rgba(100,180,255,0.3)" }}>
            loading…
          </div>
        )}
      </div>
    </div>
  );
}
