"use client";

import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { GalaxyPanel } from "@/components/galaxy/galaxy-panel";

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

export default function SystemPage() {
  return (
    <Suspense fallback={<div style={{ background: "#01040a", height: "100vh" }} />}>
      <SystemPageInner />
    </Suspense>
  );
}

function SystemPageInner() {
  const searchParams = useSearchParams();
  const domain = searchParams.get("domain") || "";

  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const iframeSrc = `/viz/system.html?domain=${encodeURIComponent(domain)}`;

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "node_selected") {
        setSelectedNode({ nodeType: e.data.nodeType, data: e.data.data });
        setSearchResults(null);
      } else if (e.data?.type === "node_cleared") {
        setSelectedNode(null);
      } else if (e.data?.type === "navigate_sector") {
        window.location.href = `/viz/sector?domain=${encodeURIComponent(e.data.domain)}`;
      } else if (e.data?.type === "navigate_galaxy") {
        window.location.href = "/viz";
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // WebSocket
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
            iframeRef.current?.contentWindow?.postMessage({ type: "search_result", entities: data.entities }, "*");
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { reconnectTimer = setTimeout(connect, 3000); };
    }
    connect();
    return () => { clearTimeout(reconnectTimer); ws?.close(); };
  }, []);

  const handleClose = () => setSelectedNode(null);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSelectedNode(null);
    try {
      const resp = await fetch(`${API_URL}/search?q=${encodeURIComponent(searchQuery.trim())}&top_k=20`);
      const results: SearchResult = await resp.json();
      setSearchResults(results);
      if (results.entities.length > 0) {
        const entityNames = results.entities.slice(0, 10).map(e => e.name);
        iframeRef.current?.contentWindow?.postMessage({ type: "search_result", entities: entityNames }, "*");
      }
    } catch (e) { console.error("Search failed:", e); }
    setSearching(false);
  }, [searchQuery]);

  const showPanel = selectedNode !== null;

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
          placeholder="search entities..."
          style={{
            width: 320, padding: "8px 14px", fontSize: 12,
            fontFamily: "'Courier New', monospace",
            background: "rgba(6,13,34,0.85)", color: "#e8eaf0",
            border: "1px solid rgba(160,130,220,0.2)", borderRadius: 6,
            outline: "none",
          }}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{
            padding: "8px 14px", fontSize: 11,
            fontFamily: "'Courier New', monospace",
            background: "rgba(160,130,220,0.1)", color: "rgba(160,130,220,0.7)",
            border: "1px solid rgba(160,130,220,0.2)", borderRadius: 6,
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
        title="System View"
      />

      {showPanel && (
        <div style={{ position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10 }}>
          <GalaxyPanel selectedNode={selectedNode} domainColors={{}} onClose={handleClose} />
        </div>
      )}
    </div>
  );
}
