// ABOUTME: Origin guard for postMessage traffic from the viz iframes.
// ABOUTME: Every window "message" listener must call this before reading event data.

/**
 * True when a MessageEvent came from our own origin.
 *
 * The viz tiers (`/viz/index.html`, `star.html`, `collection.html`) are served by the
 * same Next app that embeds them, so legitimate traffic is always same-origin. Without
 * this check `window.addEventListener("message", ...)` accepts messages from ANY frame
 * or window that has a handle to ours — an embedding page, a popup opener, an ad frame —
 * and the payloads drive real behaviour: opening documents, navigating tiers, and
 * issuing commentary requests.
 *
 * `e.origin` is set by the browser and cannot be forged by the sender, which is what
 * makes it worth checking and `e.data` not.
 */
export function isSameOriginMessage(e: MessageEvent): boolean {
  // Some browsers report "null" (the string) for sandboxed/opaque origins; treating
  // that as untrusted is correct — a real same-origin frame reports the real origin.
  return e.origin === window.location.origin;
}
