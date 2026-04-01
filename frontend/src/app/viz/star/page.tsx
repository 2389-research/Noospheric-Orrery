"use client";

import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ReaderPane } from "@/components/reader/reader-pane";

export default function StarPage() {
  return (
    <Suspense fallback={<div style={{ background: "#01040a", height: "100vh" }} />}>
      <StarPageInner />
    </Suspense>
  );
}

function StarPageInner() {
  const searchParams = useSearchParams();
  const entity = searchParams.get("entity") || "";

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const iframeSrc = `/viz/star.html?entity=${encodeURIComponent(entity)}`;

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "node_selected" && e.data.nodeType === "document") {
        setSelectedDocId(e.data.data.id as string);
      } else if (e.data?.type === "node_cleared") {
        setSelectedDocId(null);
      } else if (e.data?.type === "navigate_galaxy") {
        window.location.href = "/viz";
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // WebSocket
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
            iframeRef.current?.contentWindow?.postMessage({ type: "search_result", entities: data.entities }, "*");
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { reconnectTimer = setTimeout(connect, 3000); };
    }
    connect();
    return () => { clearTimeout(reconnectTimer); ws?.close(); };
  }, []);

  const handleClose = () => setSelectedDocId(null);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const resp = await fetch(`/api/search?q=${encodeURIComponent(searchQuery.trim())}&top_k=20`);
      const results = await resp.json();
      // Forward entity names + doc IDs from chunks to the viz
      const entityNames = (results.entities || []).slice(0, 10).map((e: { name: string }) => e.name);
      const docIds = [...new Set((results.chunks || []).map((c: { document_id: string }) => c.document_id))];
      iframeRef.current?.contentWindow?.postMessage({
        type: "search_result",
        entities: entityNames,
        doc_ids: docIds,
      }, "*");
    } catch (e) { console.error("Search failed:", e); }
    setSearching(false);
  }, [searchQuery]);

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
          placeholder="search..."
          style={{
            width: 320, padding: "8px 14px", fontSize: 12,
            fontFamily: "'Courier New', monospace",
            background: "rgba(6,13,34,0.85)", color: "#e8eaf0",
            border: "1px solid rgba(100,200,180,0.2)", borderRadius: 6,
            outline: "none",
          }}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{
            padding: "8px 14px", fontSize: 11,
            fontFamily: "'Courier New', monospace",
            background: "rgba(100,200,180,0.1)", color: "rgba(100,200,180,0.7)",
            border: "1px solid rgba(100,200,180,0.2)", borderRadius: 6,
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
        title="Star View"
      />

      {selectedDocId && (
        <div style={{
          position: "absolute", top: 0, left: 0, height: "100%", zIndex: 10,
          width: "50%", maxWidth: 600, minWidth: 360,
          background: "rgba(6,13,34,0.98)",
          borderRight: "1px solid rgba(100,200,180,0.12)",
          overflowY: "auto",
        }}>
          <ReaderPane
            documentId={selectedDocId}
            onClose={() => setSelectedDocId(null)}
            onNavigateEntity={(entityId) => {
              setSelectedDocId(null);
              // Navigate star view to this entity
              iframeRef.current?.contentWindow?.location.replace(
                `/viz/star.html?entity=${encodeURIComponent(entityId)}`
              );
              // Update URL without full page reload
              window.history.pushState({}, '', `/viz/star?entity=${encodeURIComponent(entityId)}`);
            }}
          />
        </div>
      )}
    </div>
  );
}
