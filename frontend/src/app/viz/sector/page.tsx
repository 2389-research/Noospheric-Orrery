"use client";

import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { GalaxyPanel } from "@/components/galaxy/galaxy-panel";

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

export default function SectorPage() {
  return (
    <Suspense fallback={<div style={{ background: "#01040a", height: "100vh" }} />}>
      <SectorPageInner />
    </Suspense>
  );
}

function SectorPageInner() {
  const searchParams = useSearchParams();
  const domain = searchParams.get("domain") || "";
  const cluster = searchParams.get("cluster") || "0";

  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [domainColors, setDomainColors] = useState<Record<string, string>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const iframeSrc = domain
    ? `/viz/sector.html?domain=${encodeURIComponent(domain)}`
    : `/viz/sector.html?cluster=${cluster}`;

  // Listen for postMessage
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "node_selected") {
        setSelectedNode({ nodeType: e.data.nodeType, data: e.data.data });
        setSearchResults(null);
      } else if (e.data?.type === "node_cleared") {
        setSelectedNode(null);
      } else if (e.data?.type === "navigate_galaxy") {
        window.location.href = "/viz";
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // WebSocket for search broadcasts
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
            iframeRef.current?.contentWindow?.postMessage({
              type: "search_result",
              entities: data.entities,
            }, "*");
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000);
      };
    }
    connect();
    return () => { clearTimeout(reconnectTimer); ws?.close(); };
  }, []);

  const handleClose = () => {
    setSelectedNode(null);
  };

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSelectedNode(null);
    try {
      const resp = await fetch(`/api/search?q=${encodeURIComponent(searchQuery.trim())}&top_k=20`);
      const results: SearchResult = await resp.json();
      setSearchResults(results);

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
    <div style={{ height: "calc(100vh - 57px)", position: "relative", overflow: "hidden", margin: "-24px" }}>
      {/* Search bar */}
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
            border: "1px solid rgba(200,120,80,0.2)", borderRadius: 6,
            outline: "none",
          }}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{
            padding: "8px 14px", fontSize: 11,
            fontFamily: "'Courier New', monospace",
            background: "rgba(200,120,80,0.1)", color: "rgba(200,120,80,0.7)",
            border: "1px solid rgba(200,120,80,0.2)", borderRadius: 6,
            cursor: "pointer",
          }}
        >
          {searching ? "..." : "search"}
        </button>
      </div>

      <iframe
        ref={iframeRef}
        src={iframeSrc}
        style={{ width: "100%", height: "100%", border: "none", position: "absolute", top: 0, left: 0 }}
        title="Sector View"
      />

      {showPanel && (
        <div style={{ position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10 }}>
          <GalaxyPanel selectedNode={selectedNode} domainColors={domainColors} onClose={handleClose} />
        </div>
      )}

      {showSearchResults && (
        <div style={{
          position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10,
          width: 340, background: "rgba(6,13,34,0.97)",
          borderRight: "1px solid rgba(200,120,80,0.12)",
          overflowY: "auto", fontFamily: "'Courier New', monospace",
          scrollbarWidth: "thin",
        }}>
          <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid rgba(200,120,80,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 9, color: "rgba(200,120,80,0.6)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Search Results
              </div>
              <button
                onClick={() => setSearchResults(null)}
                style={{ background: "none", border: "none", color: "rgba(200,120,80,0.6)", cursor: "pointer", fontSize: 14 }}
              >×</button>
            </div>
            <div style={{ fontSize: 14, color: "#e8eaf0", marginTop: 4 }}>
              &ldquo;{searchResults.query}&rdquo;
            </div>
            <div style={{ fontSize: 10, color: "rgba(200,120,80,0.6)", marginTop: 4 }}>
              {searchResults.total_entities} entities · {searchResults.total_chunks} chunks
            </div>
          </div>

          <div style={{ padding: "12px 16px" }}>
            {searchResults.entities.slice(0, 12).map((e) => (
              <div key={e.id} style={{
                display: "flex", alignItems: "center", gap: 8, padding: "4px 0",
                borderBottom: "1px solid rgba(200,120,80,0.04)",
              }}>
                <span style={{ fontSize: 11, color: "#e8eaf0", flex: 1 }}>{e.name}</span>
                <span style={{ fontSize: 9, color: "rgba(200,120,80,0.6)" }}>{e.type}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
