"use client";

import { createContext, useContext } from "react";

/**
 * Demo mode context — set by the noosphere layout when viewing
 * the Magos demo workspace. Components read this to hide write UI.
 */
export const DemoModeContext = createContext(false);

export function useDemoMode(): boolean {
  return useContext(DemoModeContext);
}
