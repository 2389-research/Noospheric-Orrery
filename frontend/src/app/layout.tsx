import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { UserMenu } from "@/components/user-menu";

export const metadata: Metadata = {
  title: "Noospheric Orrery",
  description: "Adaptive knowledge graph extraction pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background font-mono text-foreground antialiased">
        <AuthProvider>
          <nav className="border-b border-border/50 px-6 py-3 flex gap-6 items-center bg-card/50">
            <span className="font-semibold text-sm tracking-widest text-muted-foreground uppercase">Noospheric Orrery</span>
            <div className="flex gap-4 ml-4">
              <Link href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Upload</Link>
              <Link href="/pipeline" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Pipeline</Link>
              <Link href="/entities" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Entities</Link>
              <Link href="/viz" className="text-xs text-muted-foreground hover:text-foreground transition-colors">Galaxy</Link>
            </div>
            <div className="ml-auto">
              <UserMenu />
            </div>
          </nav>
          <main className="p-6">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
