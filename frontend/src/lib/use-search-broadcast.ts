// ABOUTME: One WebSocket to the orchestrator's /ws search_result broadcasts, held for
// ABOUTME: the component's lifetime. Shared by every view that animates search hits.

"use client";

import { useEffect, useRef } from "react";

export type SearchBroadcast = {
  entities: string[];
  doc_ids: string[];
};

/**
 * Subscribe to `search_result` broadcasts (manual searches, graph traversals, and
 * the ambient `viz-pulse` loop) and hand each one to `onResult`.
 *
 * The socket is opened once and reconnects on close. `onResult` is kept in a ref
 * rather than listed as a dependency, so a caller may pass a fresh closure every
 * render without disturbing the connection — which is the whole point:
 *
 * Four copies of this effect used to live in the orrery pages. Three listed `[]`;
 * the one on the live galaxy page listed `[viewMode]` even though it never read
 * viewMode. Every drill-in and drill-out therefore tore the socket down and built
 * a new one, and the closed socket's `onclose` still fired and scheduled a
 * reconnect that nothing tracked. Measured effect: 12 sockets across 3 drill
 * cycles, 7 left open at once, each delivering the same broadcast — so the iframe
 * got N duplicate postMessages and the server accumulated connections until the
 * tab closed (the office display reached 360). The `cancelled` flag plus clearing
 * `onclose` before `close()` is what stops the orphan-reconnect chain.
 */
export function useSearchBroadcast(onResult: (result: SearchBroadcast) => void): void {
  const handler = useRef(onResult);
  // Kept current in an effect, not during render — see react-hooks/refs.
  useEffect(() => {
    handler.current = onResult;
  }, [onResult]);

  useEffect(() => {
    const wsUrl =
      (window.location.protocol === "https:" ? "wss:" : "ws:") +
      "//" +
      window.location.host +
      "/api/ws";

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    // Set on unmount so a close event that lands afterwards cannot schedule a
    // reconnect the cleanup will never see. Without it each teardown leaks a socket.
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        // Only the parse is guarded. Wrapping the handler too would swallow real errors
        // from the consumer and make them look like malformed frames.
        let data: { type?: string; entities?: string[]; doc_ids?: string[] };
        try {
          data = JSON.parse(event.data);
        } catch {
          return; // a malformed frame must not kill the subscription
        }
        if (data.type === "search_result" && data.entities) {
          handler.current({ entities: data.entities, doc_ids: data.doc_ids || [] });
        }
      };
      ws.onclose = () => {
        if (!cancelled) reconnectTimer = setTimeout(connect, 3000);
      };
    }
    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      if (ws) {
        // Drop onclose FIRST: closing a socket that is still CONNECTING fires a
        // close event, which would otherwise queue a reconnect for a dead effect.
        ws.onclose = null;
        ws.close();
      }
    };
  }, []);
}
