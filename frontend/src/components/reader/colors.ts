export interface EntityColorSet {
  color: string;
  bg: string;      // rgba with 0.13 alpha
  bgSolid: string; // opaque for badges
}

export const ENTITY_COLORS: Record<string, EntityColorSet> = {
  Person:       { color: "#378ADD", bg: "rgba(55,138,221,0.13)",   bgSolid: "#1a2a3a" },
  Organization: { color: "#7F77DD", bg: "rgba(127,119,221,0.13)", bgSolid: "#2a1f2a" },
  Product:      { color: "#1D9E75", bg: "rgba(29,158,117,0.13)",  bgSolid: "#1a2a24" },
  Technology:   { color: "#BA7517", bg: "rgba(186,117,23,0.13)",  bgSolid: "#2a251a" },
  Event:        { color: "#D85A30", bg: "rgba(216,90,48,0.13)",   bgSolid: "#2a1a1a" },
  Concept:      { color: "#9c9a92", bg: "rgba(156,154,146,0.13)", bgSolid: "#1e1e2a" },
  Location:     { color: "#5DCAA5", bg: "rgba(93,202,165,0.13)",  bgSolid: "#1a2420" },
};

export const TYPE_ORDER = [
  "Person",
  "Organization",
  "Product",
  "Technology",
  "Event",
  "Concept",
  "Location",
] as const;
