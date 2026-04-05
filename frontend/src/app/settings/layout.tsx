"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { session } = useAuth();
  const pathname = usePathname();

  return (
    <div className="min-h-screen">
      <div className="flex items-center gap-4 px-6 py-3 border-b border-border/50 bg-card/50">
        <Link
          href="/"
          className="text-muted-foreground/60 hover:text-muted-foreground text-xs transition-colors"
        >
          ← Back
        </Link>
        <span className="text-border/30">|</span>
        {session?.role === "admin" && (
          <>
            <Link
              href="/settings/noospheres"
              className={`text-xs transition-colors ${
                pathname === "/settings/noospheres"
                  ? "text-foreground"
                  : "text-muted-foreground/60 hover:text-muted-foreground"
              }`}
            >
              Noospheres
            </Link>
            <Link
              href="/settings/team"
              className={`text-xs transition-colors ${
                pathname === "/settings/team"
                  ? "text-foreground"
                  : "text-muted-foreground/60 hover:text-muted-foreground"
              }`}
            >
              Team
            </Link>
          </>
        )}
      </div>
      <div className="p-6">{children}</div>
    </div>
  );
}
