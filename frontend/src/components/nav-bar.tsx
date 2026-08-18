"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserMenu } from "./user-menu";
import { NoosphereSwitcher } from "./noosphere-switcher";
import { RunningJobsIndicator } from "./running-jobs-indicator";

const TABS = [
  { label: "Upload", href: "upload", writeOnly: true },
  { label: "Pipeline", href: "pipeline", writeOnly: true },
  { label: "Entities", href: "entities", writeOnly: false },
  { label: "Documents", href: "documents", writeOnly: false },
  { label: "Orrery", href: "orrery", writeOnly: false },
];

export function NavBar({
  currentNoosphereId,
  isDemo = false,
}: {
  currentNoosphereId: string;
  isDemo?: boolean;
}) {
  const pathname = usePathname();

  const visibleTabs = isDemo ? TABS.filter((t) => !t.writeOnly) : TABS;

  return (
    <nav className="flex items-center gap-6 px-6 h-12 border-b border-border/50 bg-card/50">
      <span className="font-semibold text-sm tracking-widest text-muted-foreground uppercase">
        Noospheric Orrery
      </span>

      <NoosphereSwitcher currentId={currentNoosphereId} />

      <div className="flex items-center gap-1 ml-2">
        {visibleTabs.map((tab) => (
          <Link
            key={tab.href}
            href={`/n/${currentNoosphereId}/${tab.href}`}
            className={`px-3 py-1 text-xs tracking-wider rounded transition-colors ${
              pathname.includes(`/${tab.href}`)
                ? "text-foreground bg-accent/50"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </div>

      <div className="flex-1" />

      <RunningJobsIndicator noosphereId={currentNoosphereId} />

      <UserMenu />
    </nav>
  );
}
