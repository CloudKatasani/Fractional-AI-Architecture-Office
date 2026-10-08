import { Badge } from "../ui";

// Validated categorical order (dataviz validator, light surface): Invest, Tolerate, Migrate, Eliminate.
export const QUADRANTS = ["Invest", "Tolerate", "Migrate", "Eliminate"] as const;
export const QUADRANT_COLORS: Record<string, string> = {
  Invest: "#1f5bd6",
  Tolerate: "#0f9d8a",
  Migrate: "#e0a100",
  Eliminate: "#c62828",
};
const QUADRANT_BADGE: Record<string, string> = { Invest: "blue", Tolerate: "gray", Migrate: "amber", Eliminate: "red" };

export function QuadrantBadge({ quadrant, proposed }: { quadrant?: string | null; proposed?: boolean }) {
  if (!quadrant) return <span className="text-xs muted">—</span>;
  return (
    <Badge color={QUADRANT_BADGE[quadrant] || "gray"} title={proposed ? "Proposed by TIME Classifier — awaiting app owner" : "Approved disposition"}>
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: QUADRANT_COLORS[quadrant] }} />
      {quadrant}
      {proposed ? <span className="font-normal opacity-70">· proposed</span> : null}
    </Badge>
  );
}

export const FLAG_LABELS: Record<string, { label: string; color: string }> = {
  contract_renewal: { label: "renewal ≤180d", color: "gray" },
  eol_framework: { label: "EOL framework", color: "amber" },
  low_seat_utilization: { label: "low seat use", color: "amber" },
  zombie_app: { label: "zombie (0 users)", color: "red" },
  vendor_eos: { label: "vendor EOS", color: "red" },
  auto_renew_soon: { label: "auto-renew soon", color: "red" },
  untagged_cloud: { label: "untagged cloud", color: "amber" },
};

export function FlagBadge({ flag }: { flag: string }) {
  const f = FLAG_LABELS[flag] || { label: flag.replace(/_/g, " "), color: "gray" };
  return <Badge color={f.color}>{f.label}</Badge>;
}

export const humanize = (s?: string | null) => (s ? s.replace(/_/g, " ") : "");
