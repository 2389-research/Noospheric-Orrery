import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Noospheric Orrery",
  description: "Adaptive knowledge graph extraction pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background">
        <nav className="border-b px-6 py-3 flex gap-6 items-center">
          <span className="font-semibold text-lg">Noospheric Orrery</span>
          <Link href="/" className="text-sm hover:underline">Upload</Link>
          <Link href="/pipeline" className="text-sm hover:underline">Pipeline</Link>
          <Link href="/entities" className="text-sm hover:underline">Entities</Link>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
