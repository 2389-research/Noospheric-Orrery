"use client";

import { useAuth } from "@/lib/auth-context";

export function Landing() {
  const { signIn } = useAuth();

  return (
    <div className="min-h-[calc(100vh-57px)] flex flex-col items-center justify-center gap-8 px-6">
      <div className="text-center space-y-4 max-w-lg">
        <h1 className="text-2xl font-light tracking-[8px] text-muted-foreground uppercase">
          Orrery
        </h1>
        <p className="text-sm text-muted-foreground/70 leading-relaxed">
          An adaptive knowledge graph. Upload documents, discover domains,
          extract entities, and explore the result as an interactive galaxy map.
        </p>
      </div>

      <div className="flex flex-col items-center gap-4">
        <button
          onClick={signIn}
          className="flex items-center gap-3 px-6 py-3 rounded-lg border border-border/50 bg-card/50 hover:bg-card hover:border-border transition-all group"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
          </svg>
          <span className="text-sm text-foreground/80 group-hover:text-foreground transition-colors">
            Sign in with Google
          </span>
        </button>
        <span className="text-[10px] text-muted-foreground/70">
          Sign in to access your knowledge graph
        </span>
      </div>

      <div className="mt-8 grid grid-cols-3 gap-6 max-w-md text-center">
        <div className="space-y-1">
          <div className="text-lg text-muted-foreground/30">01</div>
          <div className="text-[10px] text-muted-foreground/70 uppercase tracking-wider">Upload</div>
          <div className="text-[10px] text-muted-foreground/30">Drop docs in</div>
        </div>
        <div className="space-y-1">
          <div className="text-lg text-muted-foreground/30">02</div>
          <div className="text-[10px] text-muted-foreground/70 uppercase tracking-wider">Extract</div>
          <div className="text-[10px] text-muted-foreground/30">Entities emerge</div>
        </div>
        <div className="space-y-1">
          <div className="text-lg text-muted-foreground/30">03</div>
          <div className="text-[10px] text-muted-foreground/70 uppercase tracking-wider">Explore</div>
          <div className="text-[10px] text-muted-foreground/30">Galaxy map</div>
        </div>
      </div>
    </div>
  );
}
