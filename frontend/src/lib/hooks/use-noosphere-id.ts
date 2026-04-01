"use client";

import { useParams } from "next/navigation";

/**
 * Get the current noosphereId from the URL.
 * Must be called from a component under /n/[noosphereId]/...
 */
export function useNoosphereId(): string {
  const params = useParams<{ noosphereId: string }>();
  return params.noosphereId;
}
