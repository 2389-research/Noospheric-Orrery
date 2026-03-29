"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { GalaxyPanel } from "@/components/galaxy/galaxy-panel";
import { api } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100";

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

export default function VizPage() {
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [domainColors, setDomainColors] = useState<Record<string, string>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Listen for postMessage events from the viz iframe
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "node_selected") {
        setSelectedNode({ nodeType: e.data.nodeType, data: e.data.data });
        setSearchResults(null); // clear search when selecting a node
      } else if (e.data?.type === "node_cleared") {
        setSelectedNode(null);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Subscribe to WebSocket for real-time search broadcasts (from agents, API, etc.)
  useEffect(() => {
    const wsUrl = API_URL.replace("http", "ws") + "/ws";
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "search_result" && data.entities) {
            // Forward to viz iframe
            iframeRef.current?.contentWindow?.postMessage({
              type: "search_result",
              entities: data.entities,
            }, "*");
          }
        } catch { /* ignore bad messages */ }
      };
      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000);
      };
    }
    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

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

  const handleClose = () => {
    setSelectedNode(null);
    iframeRef.current?.contentWindow?.postMessage({ type: "panel_closed" }, "*");
  };

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSelectedNode(null); // close panel during search
    try {
      const resp = await fetch(`${API_URL}/search?q=${encodeURIComponent(searchQuery.trim())}&top_k=20`);
      const results: SearchResult = await resp.json();
      setSearchResults(results);

      // Fire glow in the galaxy viz
      if (results.entities.length > 0) {
        const entityNames = results.entities.slice(0, 10).map(e => e.name);
        iframeRef.current?.contentWindow?.postMessage({
          type: "search_result",
          entities: entityNames,
        }, "*");
      }
    } catch (e) {
      console.error("Search failed:", e);
    }
    setSearching(false);
  }, [searchQuery]);

  const showPanel = selectedNode !== null;
  const showSearchResults = searchResults !== null && !showPanel;

  return (
    <div style={{ height: "calc(100vh - 57px)", position: "relative", overflow: "hidden" }}>
      {/* Search bar — overlaid top center */}
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

      <iframe
        ref={iframeRef}
        src="/viz/index.html"
        style={{ width: "100%", height: "100%", border: "none", position: "absolute", top: 0, left: 0 }}
        title="Cosmic Knowledge Graph"
      />

      {/* Galaxy panel for node selection */}
      {showPanel && (
        <div style={{ position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10 }}>
          <GalaxyPanel selectedNode={selectedNode} domainColors={domainColors} onClose={handleClose} />
        </div>
      )}

      {/* Search results panel */}
      {showSearchResults && (
        <div style={{
          position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10,
          width: 340, background: "rgba(6,13,34,0.97)",
          borderRight: "1px solid rgba(100,180,255,0.12)",
          overflowY: "auto", fontFamily: "'Courier New', monospace",
          scrollbarWidth: "thin", scrollbarColor: "rgba(100,180,255,0.2) transparent",
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

          {/* Entity results */}
          <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(100,180,255,0.08)" }}>
            <div style={{ fontSize: 9, color: "rgba(140,200,255,0.6)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
              Entities
            </div>
            {searchResults.entities.slice(0, 12).map((e) => {
              const typeColors: Record<string, string> = {
                Person: "#378ADD", Organization: "#7F77DD", Product: "#1D9E75",
                Technology: "#BA7517", Event: "#D85A30", Concept: "#9c9a92", Location: "#5DCAA5",
              };
              return (
                <div key={e.id} style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "4px 0",
                  borderBottom: "1px solid rgba(100,180,255,0.04)",
                }}>
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
                  <span style={{ fontSize: 9, color: "rgba(140,200,255,0.4)", flexShrink: 0 }}>
                    {e.score.toFixed(3)}
                  </span>
                </div>
              );
            })}
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
