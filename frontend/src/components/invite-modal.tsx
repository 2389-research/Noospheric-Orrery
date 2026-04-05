"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export function InviteModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"editor" | "viewer">("editor");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const appUrl = typeof window !== "undefined" ? window.location.origin : "";

  async function handleInvite() {
    if (!email.trim()) {
      setError("Email required");
      return;
    }
    setLoading(true);
    try {
      await api.createInvite(email.trim().toLowerCase(), role);
      setSuccess(true);
    } catch {
      setError("Failed to create invite");
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-card border border-border/50 rounded-lg p-6 w-96">
        {!success ? (
          <>
            <h2 className="text-foreground text-sm mb-5">Invite to your Noospheres</h2>

            <label className="block text-muted-foreground/60 text-xs mb-1">Email</label>
            <input
              autoFocus
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleInvite()}
              placeholder="colleague@example.com"
              className="w-full bg-background border border-border/30 rounded px-3 py-2 text-foreground text-sm mb-4 focus:outline-none focus:border-border/60"
            />

            <label className="block text-muted-foreground/60 text-xs mb-2">Role</label>
            <div className="flex gap-3 mb-5">
              {(["editor", "viewer"] as const).map((r) => (
                <button
                  key={r}
                  onClick={() => setRole(r)}
                  className={`flex-1 py-2 px-3 rounded border text-xs transition-colors ${
                    role === r
                      ? "border-accent/50 bg-accent/20 text-foreground"
                      : "border-border/30 text-muted-foreground hover:border-border/50"
                  }`}
                >
                  <div className="capitalize">{r}</div>
                  <div className="text-[10px] mt-0.5 text-muted-foreground/60">
                    {r === "editor" ? "Can upload & run pipeline" : "Read-only access"}
                  </div>
                </button>
              ))}
            </div>

            {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-xs text-muted-foreground/60 hover:text-muted-foreground">
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={loading}
                className="px-4 py-2 text-xs bg-accent/30 border border-accent/50 text-foreground rounded hover:bg-accent/50 disabled:opacity-40"
              >
                {loading ? "Sending..." : "Create Invite"}
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-foreground text-sm mb-3">Invite created</h2>
            <p className="text-muted-foreground/70 text-xs mb-1">
              Share this URL with <span className="text-foreground/80">{email}</span>.
            </p>
            <p className="text-muted-foreground/70 text-xs mb-5">
              When they sign in with Google, they&apos;ll automatically join your org.
            </p>
            <div className="flex gap-2 p-2 rounded border border-border/30 bg-background mb-5">
              <code className="text-accent text-xs flex-1 truncate">{appUrl}</code>
              <button
                onClick={() => navigator.clipboard.writeText(appUrl)}
                className="text-muted-foreground/50 hover:text-muted-foreground text-xs"
              >
                Copy
              </button>
            </div>
            <div className="flex justify-end">
              <button
                onClick={onCreated}
                className="px-4 py-2 text-xs bg-accent/30 border border-accent/50 text-foreground rounded hover:bg-accent/50"
              >
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
