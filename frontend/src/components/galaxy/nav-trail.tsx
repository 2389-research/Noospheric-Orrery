"use client";

export interface TrailItem {
  name: string;
  nodeType: "entity" | "domain" | "trade_route" | "collection";
  id: string;
}

interface NavTrailProps {
  trail: TrailItem[];
  onNavigate: (item: TrailItem, index: number) => void;
}

export function NavTrail({ trail, onNavigate }: NavTrailProps) {
  if (trail.length <= 1) return null;

  return (
    <div
      style={{
        padding: "6px 14px",
        borderBottom: "1px solid rgba(100,180,255,0.08)",
        display: "flex",
        alignItems: "center",
        gap: 4,
        flexWrap: "wrap",
        fontFamily: "'Courier New', monospace",
        fontSize: 10,
        overflowX: "auto",
        whiteSpace: "nowrap",
      }}
    >
      {trail.map((item, index) => {
        const isCurrent = index === trail.length - 1;
        return (
          <span key={index} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {index > 0 && (
              <span style={{ color: "rgba(100,180,255,0.25)" }}>›</span>
            )}
            {isCurrent ? (
              <span style={{ color: "rgba(100,180,255,0.85)" }}>{item.name}</span>
            ) : (
              <button
                onClick={() => onNavigate(item, index)}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  color: "rgba(140,200,255,0.65)",
                  fontFamily: "'Courier New', monospace",
                  fontSize: 10,
                  textDecoration: "underline",
                  textDecorationColor: "rgba(100,180,255,0.2)",
                }}
              >
                {item.name}
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}
