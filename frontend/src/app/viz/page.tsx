"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { GalaxyPanel } from "@/components/galaxy/galaxy-panel";
import { ReaderPane } from "@/components/reader/reader-pane";
import { api } from "@/lib/api";

interface SelectedNode {
  nodeType: string;
  data: Record<string, unknown>;
}

interface SearchResult {
  query: string;
  entities: { id: string; name: string; type: string; source_count: number; score: number; paths: string[] }[];
  chunks: { chunk_id: string; document_id: string; document_title: string; text: string; score: number }[];
  total_entities: number;
  total_chunks: number;
}

type ViewMode = "galaxy" | "star";

interface Breadcrumb {
  label: string;
  action: () => void;
}

export default function VizPage() {
  const [viewMode, setViewMode] = useState<ViewMode>("galaxy");
  const [starEntityId, setStarEntityId] = useState<string | null>(null);
  const [starEntityName, setStarEntityName] = useState<string>("");
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [domainColors, setDomainColors] = useState<Record<string, string>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [fading, setFading] = useState(false);
  const galaxyRef = useRef<HTMLIFrameElement>(null);
  const starRef = useRef<HTMLIFrameElement>(null);

  // Current iframe ref
  const activeRef = viewMode === "star" ? starRef : galaxyRef;

  // Breadcrumbs
  const breadcrumbs: Breadcrumb[] = [
    { label: "Galaxy", action: () => exitStarView() },
  ];
  if (viewMode === "star" && starEntityName) {
    breadcrumbs.push({ label: starEntityName, action: () => {} });
  }

  // Enter star view with fade
  const enterStarView = useCallback((entityId: string, entityName: string) => {
    setFading(true);
    setTimeout(() => {
      setStarEntityId(entityId);
      setStarEntityName(entityName);
      setViewMode("star");
      setSelectedNode(null);
      setSearchResults(null);
      setSelectedDocId(null);
      setTimeout(() => setFading(false), 50);
    }, 300);
  }, []);

  // Exit star view
  const exitStarView = useCallback(() => {
    setFading(true);
    setTimeout(() => {
      setViewMode("galaxy");
      setStarEntityId(null);
      setStarEntityName("");
      setSelectedNode(null);
      setSelectedDocId(null);
      setTimeout(() => setFading(false), 50);
    }, 300);
  }, []);

  // Reset to galaxy home
  const resetGalaxy = useCallback(() => {
    if (viewMode === "star") {
      exitStarView();
    }
    setTimeout(() => {
      galaxyRef.current?.contentWindow?.postMessage({ type: "reset_galaxy" }, "*");
    }, viewMode === "star" ? 400 : 0);
  }, [viewMode, exitStarView]);

  // Listen for postMessage events
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "node_selected") {
        if (e.data.nodeType === "document") {
          setSelectedDocId(e.data.data.id as string);
          setSelectedNode(null);
        } else {
          setSelectedNode({ nodeType: e.data.nodeType, data: e.data.data });
          setSelectedDocId(null);
          setSearchResults(null);
        }
      } else if (e.data?.type === "node_cleared") {
        setSelectedNode(null);
        setSelectedDocId(null);
      } else if (e.data?.type === "enter_star") {
        enterStarView(e.data.entityId, e.data.entityName);
      } else if (e.data?.type === "navigate_galaxy") {
        exitStarView();
      } else if (e.data?.type === "reset_home") {
        exitStarView();
        // After fade back, reset galaxy camera to full overview
        setTimeout(() => {
          galaxyRef.current?.contentWindow?.postMessage({ type: "reset_galaxy" }, "*");
        }, 400);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [enterStarView, exitStarView]);

  // WebSocket for real-time search broadcasts
  useEffect(() => {
    const wsUrl = (window.location.protocol === "https:" ? "wss:" : "ws:") + "//" + window.location.host + "/api/ws";
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    function connect() {
      ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "search_result" && data.entities) {
            activeRef.current?.contentWindow?.postMessage({
              type: "search_result",
              entities: data.entities,
            }, "*");
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { reconnectTimer = setTimeout(connect, 3000); };
    }
    connect();
    return () => { clearTimeout(reconnectTimer); ws?.close(); };
  }, [viewMode]);

  // Fetch domain colors
  useEffect(() => {
    (async () => {
      try {
        const domains = await api.getDomains();
        const palette = ["#378ADD","#7F77DD","#1D9E75","#BA7517","#D85A30","#5DCAA5","#9c9a92","#4a90d9","#9b59b6","#2ecc71"];
        const colors: Record<string, string> = {};
        domains.forEach((d, i) => { colors[d.path] = palette[i % palette.length]; });
        setDomainColors(colors);
      } catch { /* cosmetic */ }
    })();
  }, []);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSelectedNode(null);
    setSelectedDocId(null);
    try {
      const resp = await fetch(`/api/search?q=${encodeURIComponent(searchQuery.trim())}&top_k=20`);
      const results: SearchResult = await resp.json();
      setSearchResults(results);

      // Fire glow in active viz
      const entityNames = results.entities.slice(0, 10).map(e => e.name);
      const docIds = [...new Set(results.chunks.map(c => c.document_id))];
      activeRef.current?.contentWindow?.postMessage({
        type: "search_result",
        entities: entityNames,
        doc_ids: docIds,
      }, "*");
    } catch (e) {
      console.error("Search failed:", e);
    }
    setSearching(false);
  }, [searchQuery, viewMode]);

  // Click search result → navigate to it
  const flyToEntity = useCallback((entityId: string) => {
    if (viewMode === "star") {
      // In star mode, navigate to that entity's star view
      enterStarView(entityId, "");
    } else {
      galaxyRef.current?.contentWindow?.postMessage({
        type: "fly_to_entity", entityId,
      }, "*");
    }
    setSearchResults(null);
  }, [viewMode, enterStarView]);

  const flyToDomain = useCallback((domainPath: string) => {
    if (viewMode === "star") exitStarView();
    setTimeout(() => {
      galaxyRef.current?.contentWindow?.postMessage({
        type: "fly_to_domain", domainPath,
      }, "*");
    }, viewMode === "star" ? 400 : 0);
    setSearchResults(null);
  }, [viewMode, exitStarView]);

  const showPanel = selectedNode !== null;
  const showDoc = selectedDocId !== null;
  const showSearchResults = searchResults !== null && !showPanel && !showDoc;

  const typeColors: Record<string, string> = {
    Person: "#378ADD", Organization: "#7F77DD", Product: "#1D9E75",
    Technology: "#BA7517", Event: "#D85A30", Concept: "#9c9a92", Location: "#5DCAA5",
  };

  return (
    <div style={{ height: "calc(100vh - 57px)", position: "relative", overflow: "hidden", margin: "-24px" }}>
      {/* Search bar — top center */}
      <div style={{
        position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
        zIndex: 20, display: "flex", gap: 6,
      }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="search the knowledge graph..."
          style={{
            width: 320, padding: "8px 14px", fontSize: 12,
            fontFamily: "'Courier New', monospace",
            background: "rgba(6,13,34,0.85)", color: "#e8eaf0",
            border: "1px solid rgba(100,180,255,0.2)", borderRadius: 6,
            outline: "none",
          }}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{
            padding: "8px 14px", fontSize: 11,
            fontFamily: "'Courier New', monospace",
            background: "rgba(100,180,255,0.1)", color: "rgba(100,180,255,0.7)",
            border: "1px solid rgba(100,180,255,0.2)", borderRadius: 6,
            cursor: "pointer",
          }}
        >
          {searching ? "..." : "search"}
        </button>
      </div>

      {/* Breadcrumb + nav — top left, hidden when panel is open */}
      <div style={{
        position: "absolute", top: 12, left: 14, zIndex: 20,
        display: (showPanel || showDoc || showSearchResults || viewMode === "star") ? "none" : "flex",
        alignItems: "center", gap: 8,
        fontFamily: "'Courier New', monospace",
      }}>
        <button
          onClick={resetGalaxy}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "rgba(100,180,255,0.7)", fontSize: 14,
          }}
          title="Reset to galaxy view"
        >⌂</button>
        {breadcrumbs.map((bc, i) => (
          <span key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {i > 0 && <span style={{ color: "rgba(100,180,255,0.3)", fontSize: 10 }}>›</span>}
            <button
              onClick={bc.action}
              style={{
                background: "none", border: "none", cursor: i < breadcrumbs.length - 1 ? "pointer" : "default",
                color: i < breadcrumbs.length - 1 ? "rgba(100,180,255,0.6)" : "rgba(100,180,255,0.9)",
                fontSize: 10, letterSpacing: "0.05em",
                fontFamily: "'Courier New', monospace",
              }}
            >{bc.label}</button>
          </span>
        ))}
      </div>

      {/* Fade overlay */}
      <div style={{
        position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
        background: "#01040a", zIndex: 15, pointerEvents: "none",
        opacity: fading ? 1 : 0,
        transition: "opacity 0.3s ease",
      }} />

      {/* Galaxy/Sector iframe (always mounted, hidden when in star mode) */}
      <iframe
        ref={galaxyRef}
        src="/viz/index.html"
        style={{
          width: "100%", height: "100%", border: "none",
          position: "absolute", top: 0, left: 0,
          display: viewMode === "galaxy" ? "block" : "none",
        }}
        title="Galaxy View"
      />

      {/* Star iframe (mounted when in star mode) */}
      {viewMode === "star" && starEntityId && (
        <iframe
          ref={starRef}
          src={`/viz/star.html?entity=${encodeURIComponent(starEntityId)}`}
          style={{
            width: "100%", height: "100%", border: "none",
            position: "absolute", top: 0, left: 0,
          }}
          title="Star View"
        />
      )}

      {/* Left panel: node details / doc reader / search results */}
      {showPanel && (
        <div style={{ position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10 }}>
          <GalaxyPanel
            selectedNode={selectedNode}
            domainColors={domainColors}
            onClose={() => {
              setSelectedNode(null);
              activeRef.current?.contentWindow?.postMessage({ type: "panel_closed" }, "*");
            }}
            onNavigateToEntity={(entityId) => {
              galaxyRef.current?.contentWindow?.postMessage({
                type: "fly_to_entity", entityId,
              }, "*");
            }}
            onNavigateToDomain={(domainPath) => {
              galaxyRef.current?.contentWindow?.postMessage({
                type: "fly_to_domain", domainPath,
              }, "*");
            }}
          />
        </div>
      )}

      {showDoc && (
        <div style={{
          position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10,
          width: "50%", maxWidth: 600, minWidth: 360,
          background: "rgba(6,13,34,0.98)",
          borderRight: "1px solid rgba(100,200,180,0.12)",
          overflowY: "auto",
        }}>
          <ReaderPane
            documentId={selectedDocId!}
            onClose={() => setSelectedDocId(null)}
            onNavigateEntity={(entityId) => {
              setSelectedDocId(null);
              enterStarView(entityId, "");
            }}
          />
        </div>
      )}

      {showSearchResults && (
        <div style={{
          position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10,
          width: 340, background: "rgba(6,13,34,0.97)",
          borderRight: "1px solid rgba(100,180,255,0.12)",
          overflowY: "auto", fontFamily: "'Courier New', monospace",
          scrollbarWidth: "thin",
        }}>
          {/* Header */}
          <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid rgba(100,180,255,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Search Results
              </div>
              <button
                onClick={() => setSearchResults(null)}
                style={{ background: "none", border: "none", color: "rgba(140,200,255,0.6)", cursor: "pointer", fontSize: 14 }}
              >×</button>
            </div>
            <div style={{ fontSize: 14, color: "#e8eaf0", marginTop: 4 }}>
              &ldquo;{searchResults.query}&rdquo;
            </div>
            <div style={{ fontSize: 10, color: "rgba(140,200,255,0.6)", marginTop: 4 }}>
              {searchResults.total_entities} entities · {searchResults.total_chunks} chunks
            </div>
          </div>

          {/* Entity results — clickable → fly to */}
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,180,255,0.08)" }}>
            <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
              Entities — click to locate
            </div>
            {searchResults.entities.slice(0, 12).map((e) => (
              <div
                key={e.id}
                onClick={() => flyToEntity(e.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "5px 4px",
                  borderBottom: "1px solid rgba(100,180,255,0.04)",
                  cursor: "pointer", borderRadius: 3,
                  transition: "background 0.1s",
                }}
                onMouseEnter={(ev) => (ev.currentTarget.style.background = "rgba(100,180,255,0.06)")}
                onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
              >
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: typeColors[e.type] || "#9c9a92", flexShrink: 0,
                }} />
                <span style={{ fontSize: 11, color: "#e8eaf0", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {e.name}
                </span>
                <span style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", flexShrink: 0 }}>
                  {e.type}
                </span>
              </div>
            ))}
          </div>

          {/* Chunk results */}
          <div style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
              Document Excerpts
            </div>
            {searchResults.chunks.slice(0, 5).map((c, i) => (
              <div key={i} style={{
                padding: "8px 10px", marginBottom: 8,
                borderLeft: "2px solid rgba(0,200,180,0.4)",
                background: "rgba(100,180,255,0.03)", borderRadius: "0 3px 3px 0",
              }}>
                <div style={{ fontSize: 10, color: "rgba(140,200,255,0.6)", marginBottom: 4 }}>
                  {c.document_title}
                </div>
                <div style={{ fontSize: 11, color: "rgba(200,215,235,0.85)", lineHeight: 1.5 }}>
                  {c.text}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
