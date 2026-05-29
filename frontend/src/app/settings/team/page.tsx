"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useMembers } from "@/lib/hooks/use-members";
import { useInvites } from "@/lib/hooks/use-invites";
import { api } from "@/lib/api";
import { InviteModal } from "@/components/invite-modal";

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
};

function MemberRow({ member, isSelf }: { member: { id: string; email: string; role: string }; isSelf: boolean }) {
  return (
    <div className="flex items-center justify-between p-3 rounded border border-border/30">
      <div>
        <span className="text-foreground text-xs">{member.email}</span>
        {isSelf && <span className="ml-2 text-muted-foreground/70 text-[10px]">(you)</span>}
      </div>
      <span className="text-muted-foreground/70 text-[10px] capitalize">
        {ROLE_LABELS[member.role] ?? member.role}
      </span>
    </div>
  );
}

function InviteRow({ invite, onRevoke }: { invite: { id: string; email: string; role: string; createdAt: string }; onRevoke: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const age = Math.floor((Date.now() - new Date(invite.createdAt).getTime()) / 86400000);

  return (
    <div className="flex items-center justify-between p-3 rounded border border-border/30 group">
      <div>
        <span className="text-muted-foreground text-xs">{invite.email}</span>
        <div className="flex gap-3 mt-0.5">
          <span className="text-muted-foreground/70 text-[10px]">{ROLE_LABELS[invite.role] ?? invite.role}</span>
          <span className="text-muted-foreground/70 text-[10px]">
            Invited {age === 0 ? "today" : `${age}d ago`}
          </span>
        </div>
      </div>
      {!confirming ? (
        <button
          onClick={() => setConfirming(true)}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground/30 hover:text-red-400/70 text-xs px-2 py-1 transition-all"
        >
          Revoke
        </button>
      ) : (
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground/70 text-[10px]">Sure?</span>
          <button onClick={onRevoke} className="text-red-400 text-xs px-2 py-1">Yes</button>
          <button onClick={() => setConfirming(false)} className="text-muted-foreground/70 text-xs px-2 py-1">No</button>
        </div>
      )}
    </div>
  );
}

export default function TeamSettingsPage() {
  const { user, session } = useAuth();
  const { members, loading: membersLoading } = useMembers();
  const { invites, loading: invitesLoading, refresh } = useInvites();
  const [showInvite, setShowInvite] = useState(false);
  const router = useRouter();

  if (session && session.role !== "admin") {
    router.replace("/");
    return null;
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Team</h1>
        <button
          onClick={() => setShowInvite(true)}
          className="px-3 py-1.5 text-xs border border-accent/50 text-foreground rounded hover:bg-accent/30"
        >
          + Invite someone
        </button>
      </div>

      {/* Members */}
      <section className="mb-8">
        <h2 className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-3">Members</h2>
        {membersLoading ? (
          <p className="text-muted-foreground/70 text-xs">Loading...</p>
        ) : (
          <div className="space-y-1">
            {members.map((member) => (
              <MemberRow key={member.id} member={member} isSelf={member.id === user?.uid} />
            ))}
          </div>
        )}
      </section>

      {/* Pending Invites */}
      <section>
        <h2 className="text-[9px] tracking-[2px] text-muted-foreground/70 uppercase mb-3">Pending Invites</h2>
        {invitesLoading ? (
          <p className="text-muted-foreground/70 text-xs">Loading...</p>
        ) : invites.length === 0 ? (
          <p className="text-muted-foreground/70 text-xs">No pending invites</p>
        ) : (
          <div className="space-y-1">
            {invites.map((invite) => (
              <InviteRow
                key={invite.id}
                invite={invite}
                onRevoke={async () => {
                  await api.revokeInvite(invite.id);
                  refresh();
                }}
              />
            ))}
          </div>
        )}
      </section>

      {showInvite && (
        <InviteModal
          onClose={() => setShowInvite(false)}
          onCreated={() => {
            setShowInvite(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}
