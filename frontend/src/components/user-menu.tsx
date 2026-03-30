"use client";

import { useAuth } from "@/lib/auth-context";

export function UserMenu() {
  const { user, loading, signIn, signOut } = useAuth();

  if (loading) {
    return <span className="text-[10px] text-muted-foreground/40">...</span>;
  }

  if (!user) {
    return (
      <button
        onClick={signIn}
        className="text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors border border-border/30 rounded px-2 py-1"
      >
        sign in
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {user.photoURL && (
        <img
          src={user.photoURL}
          alt=""
          className="w-5 h-5 rounded-full"
          referrerPolicy="no-referrer"
        />
      )}
      <span className="text-[10px] text-muted-foreground/70">
        {user.displayName || user.email}
      </span>
      <button
        onClick={signOut}
        className="text-[10px] text-muted-foreground/40 hover:text-muted-foreground transition-colors"
      >
        sign out
      </button>
    </div>
  );
}
