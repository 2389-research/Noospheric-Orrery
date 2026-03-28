"use client";

import { useEffect, useRef, useState } from "react";
import { GalaxyPanel } from "@/components/galaxy/galaxy-panel";
import { api } from "@/lib/api";

interface SelectedNode {
  nodeType: string;
  data: Record<string, unknown>;
}

export default function VizPage() {
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const [domainColors, setDomainColors] = useState<Record<string, string>>({});
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Listen for postMessage events from the viz iframe
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "node_selected") {
        setSelectedNode({ nodeType: e.data.nodeType, data: e.data.data });
      } else if (e.data?.type === "node_cleared") {
        setSelectedNode(null);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Fetch domain colors from domains list (used for donut arcs)
  useEffect(() => {
    (async () => {
      try {
        const domains = await api.getDomains();
        // Assign colors based on position using a fixed palette that matches cosmic aesthetic
        const palette = [
          "#378ADD",
          "#7F77DD",
          "#1D9E75",
          "#BA7517",
          "#D85A30",
          "#5DCAA5",
          "#9c9a92",
          "#4a90d9",
          "#9b59b6",
          "#2ecc71",
        ];
        const colors: Record<string, string> = {};
        domains.forEach((d, i) => {
          colors[d.path] = palette[i % palette.length];
        });
        setDomainColors(colors);
      } catch {
        // domain colors are cosmetic — silent fail
      }
    })();
  }, []);

  const handleClose = () => {
    setSelectedNode(null);
    // Also notify the iframe to unpin
    iframeRef.current?.contentWindow?.postMessage({ type: "panel_closed" }, "*");
  };

  return (
    <div className="flex" style={{ height: "calc(100vh - 57px)" }}>
      {selectedNode && (
        <GalaxyPanel
          selectedNode={selectedNode}
          domainColors={domainColors}
          onClose={handleClose}
        />
      )}
      <iframe
        ref={iframeRef}
        src="/cosmic-viz.html"
        style={{
          flex: selectedNode ? "1" : undefined,
          width: selectedNode ? undefined : "100%",
          height: "100%",
          border: "none",
        }}
        title="Cosmic Knowledge Graph"
      />
    </div>
  );
}
