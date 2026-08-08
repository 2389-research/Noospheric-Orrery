// Shared entity type → color map for the galaxy side-panels. Kept in one place
// so the four panel components (entity / domain / repo / trade-route) can't drift.

export const ENTITY_COLORS: Record<string, string> = {
  Person: "#378ADD",
  Organization: "#7F77DD",
  Product: "#1D9E75",
  Technology: "#BA7517",
  Event: "#D85A30",
  Concept: "#9c9a92",
  Location: "#5DCAA5",
};

export const ENTITY_COLOR_FALLBACK = "#9c9a92";

export function getEntityColor(type: string): string {
  return ENTITY_COLORS[type] ?? ENTITY_COLOR_FALLBACK;
}
