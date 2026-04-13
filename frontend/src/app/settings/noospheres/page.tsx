"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useWorkspaces, type Workspace } from "@/lib/hooks/use-workspaces";
import { api } from "@/lib/api";
import { CreateNoosphereModal } from "@/components/create-noosphere-modal";

function WorkspaceRow({ workspace }: { workspace: Workspace }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(workspace.name);
  const [confirming, setConfirming] = useState(false);

  async function handleRename() {
    if (name.trim() && name !== workspace.name) {
      await api.updateWorkspace(workspace.id, name.trim());
    }
    setEditing(false);
  }

  return (
    <div className="flex items-center justify-between p-3 rounded border border-border/30 hover:bg-card/50 transition-colors group">
      <div className="flex-1 min-w-0">
        {editing ? (
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => e.key === "Enter" && handleRename()}
            className="bg-transparent border-b border-accent/50 text-foreground text-xs focus:outline-none w-full"
          />
        ) : (
          <span className="text-foreground text-xs">{workspace.name}</span>
        )}
        {workspace.description && (
          <div className="text-[10px] text-muted-foreground/50 mt-0.5">{workspace.description}</div>
        )}
      </div>

      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => setEditing(true)}
          className="text-muted-foreground/50 hover:text-muted-foreground text-xs px-2 py-1"
        >
          Rename
        </button>
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            className="text-muted-foreground/30 hover:text-red-400/70 text-xs px-2 py-1"
          >
            Archive
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground/50 text-[10px]">Sure?</span>
            <button
              onClick={async () => {
                await api.archiveWorkspace(workspace.id);
                setConfirming(false);
              }}
              className="text-red-400 text-xs px-2 py-1"
            >
              Yes
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-muted-foreground/50 text-xs px-2 py-1"
            >
              No
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function NoospheresSettingsPage() {
  const { session } = useAuth();
  const { workspaces, loading, refresh } = useWorkspaces();
  const [showCreate, setShowCreate] = useState(false);
  const router = useRouter();

  if (session && session.role !== "admin") {
    router.replace("/");
    return null;
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Noospheres</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 text-xs border border-accent/50 text-foreground rounded hover:bg-accent/30"
        >
          + New Noosphere
        </button>
      </div>

      {loading ? (
        <p className="text-muted-foreground/50 text-xs">Loading...</p>
      ) : (
        <div className="space-y-2">
          {workspaces.map((ws) => (
            <WorkspaceRow key={ws.id} workspace={ws} />
          ))}
        </div>
      )}

      {showCreate && (
        <CreateNoosphereModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refresh(); }}
        />
      )}
    </div>
  );
}
