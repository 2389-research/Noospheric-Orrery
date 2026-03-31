"use client";

import { useAuth } from "@/lib/auth-context";
import { Landing } from "./landing";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  // Still loading auth state — show nothing to avoid flash
  if (loading) {
    return (
      <div className="min-h-[calc(100vh-57px)] flex items-center justify-center">
        <span className="text-[10px] text-muted-foreground/30 tracking-wider">loading...</span>
      </div>
    );
  }

  // Not signed in — show landing page
  if (!user) {
    return <Landing />;
  }

  // Authenticated — show the app
  return <>{children}</>;
}
