import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

/**
 * Switch to a different noosphere while preserving the current tab.
 */
export function switchNoosphere(
  currentPath: string,
  currentId: string,
  newId: string,
  router: AppRouterInstance,
) {
  const newPath = currentPath.replace(`/n/${currentId}`, `/n/${newId}`);
  router.push(newPath);
}
