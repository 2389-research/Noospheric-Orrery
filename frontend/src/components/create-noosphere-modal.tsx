"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export function CreateNoosphereModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate() {
    if (!name.trim()) {
      setError("Name required");
      return;
    }
    setLoading(true);
    try {
      const { workspaceId } = await api.createWorkspace(name.trim(), description.trim());
      onCreated(workspaceId);
    } catch {
      setError("Failed to create noosphere");
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-card border border-border/50 rounded-lg p-6 w-96">
        <h2 className="text-foreground text-sm mb-4">Create a Noosphere</h2>

        <label className="block text-muted-foreground/60 text-xs mb-1">Name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          placeholder="Research Notes"
          className="w-full bg-background border border-border/30 rounded px-3 py-2 text-foreground text-sm mb-3 focus:outline-none focus:border-border/60"
        />

        <label className="block text-muted-foreground/60 text-xs mb-1">
          Description <span className="text-muted-foreground/30">(optional)</span>
        </label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What will you map?"
          className="w-full bg-background border border-border/30 rounded px-3 py-2 text-foreground text-sm mb-4 focus:outline-none focus:border-border/60"
        />

        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs text-muted-foreground/60 hover:text-muted-foreground"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={loading}
            className="px-4 py-2 text-xs bg-accent/30 border border-accent/50 text-foreground rounded hover:bg-accent/50 disabled:opacity-40"
          >
            {loading ? "Creating..." : "Create Noosphere"}
          </button>
        </div>
      </div>
    </div>
  );
}
