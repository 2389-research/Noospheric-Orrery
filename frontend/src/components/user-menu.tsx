"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

export function UserMenu() {
  const { user, loading, session, signIn, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (loading) {
    return <span className="text-[10px] text-muted-foreground/70">...</span>;
  }

  if (!user) {
    return (
      <button
        onClick={signIn}
        className="text-[10px] text-muted-foreground/70 hover:text-muted-foreground transition-colors border border-border/30 rounded px-2 py-1"
      >
        sign in
      </button>
    );
  }

  const isAdmin = session?.role === "admin";

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 hover:opacity-80 transition-opacity"
      >
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
        <span className="text-muted-foreground/30 text-[10px]">▾</span>
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-1 w-48 rounded border border-border/50 bg-card shadow-xl z-50 py-1">
          <div className="px-3 py-2 border-b border-border/30">
            <div className="text-[10px] text-foreground/80 truncate">{user.email}</div>
            {session?.role && (
              <div className="text-[9px] text-muted-foreground/70 mt-0.5 capitalize">{session.role}</div>
            )}
          </div>

          {isAdmin && (
            <>
              <Link
                href="/settings/noospheres"
                onClick={() => setOpen(false)}
                className="block px-3 py-2 text-xs text-muted-foreground hover:bg-accent/30 hover:text-foreground transition-colors"
              >
                Noospheres
              </Link>
              <Link
                href="/settings/team"
                onClick={() => setOpen(false)}
                className="block px-3 py-2 text-xs text-muted-foreground hover:bg-accent/30 hover:text-foreground transition-colors"
              >
                Team Settings
              </Link>
              <div className="border-t border-border/30 my-1" />
            </>
          )}

          <button
            onClick={() => {
              setOpen(false);
              signOut();
            }}
            className="w-full text-left px-3 py-2 text-xs text-muted-foreground/70 hover:text-muted-foreground hover:bg-accent/30 transition-colors"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
