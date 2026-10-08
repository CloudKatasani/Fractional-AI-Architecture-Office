import { ReactNode, useState } from "react";

export function Card({ title, actions, children, className = "", subtitle }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; subtitle?: ReactNode;
}) {
  return (
    <div className={`card ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-4 py-2.5">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <div className="text-xs muted mt-0.5">{subtitle}</div>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, onClick, accent }: { label: string; value: ReactNode; sub?: ReactNode; onClick?: () => void; accent?: boolean }) {
  return (
    <div onClick={onClick} className={`card px-4 py-3 ${onClick ? "cursor-pointer hover:border-accent-500" : ""}`}>
      <div className="label">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${accent ? "text-accent-600" : "text-gray-900"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs muted">{sub}</div>}
    </div>
  );
}

const BADGE_COLORS: Record<string, string> = {
  gray: "bg-gray-100 text-gray-700 border-gray-200",
  green: "bg-green-50 text-green-700 border-green-200",
  amber: "bg-amber-50 text-amber-800 border-amber-200",
  red: "bg-red-50 text-red-700 border-red-200",
  blue: "bg-accent-50 text-accent-700 border-accent-100",
  purple: "bg-purple-50 text-purple-700 border-purple-200",
};

export function Badge({ children, color = "gray", title }: { children: ReactNode; color?: keyof typeof BADGE_COLORS | string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap ${BADGE_COLORS[color] || BADGE_COLORS.gray}`}>
      {children}
    </span>
  );
}

/** green >= 0.9, amber 0.7-0.9, red < 0.7 (Section 10.1) */
export function ConfidenceBadge({ value }: { value?: number | null }) {
  if (value === undefined || value === null) return null;
  const color = value >= 0.9 ? "green" : value >= 0.7 ? "amber" : "red";
  return <Badge color={color} title="Confidence">{Math.round(value * 100)}%</Badge>;
}

const TIER_COLORS: Record<string, string> = { unacceptable: "red", high: "red", limited: "amber", minimal: "green" };
export function TierBadge({ tier, proposed }: { tier?: string | null; proposed?: boolean }) {
  if (!tier) return <span className="muted text-xs">—</span>;
  return (
    <Badge color={TIER_COLORS[tier] || "gray"} title={proposed ? "Proposed by agent — awaiting risk officer" : "Approved"}>
      {tier === "unacceptable" ? "BLOCKED" : tier.toUpperCase()}
      {proposed ? " · proposed" : ""}
    </Badge>
  );
}

const SEV_COLORS: Record<string, string> = { critical: "red", high: "red", medium: "amber", low: "gray" };
export function SeverityBadge({ severity }: { severity?: string }) {
  if (!severity) return null;
  return <Badge color={SEV_COLORS[severity] || "gray"}>{severity}</Badge>;
}

export function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return null;
  const color = status === "approved" || status === "edited" ? "green" : status === "rejected" ? "red" : status === "pending" ? "amber" : "gray";
  return <Badge color={color}>{status}</Badge>;
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: ReactNode }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-gray-200 mb-4 overflow-x-auto">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${
            active === t.id ? "border-accent-600 text-accent-700" : "border-transparent text-gray-500 hover:text-gray-800"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function useTab(defaultTab: string, key: string) {
  const fromUrl = new URLSearchParams(window.location.search).get(key);
  const [tab, setTab] = useState(fromUrl || defaultTab);
  return [tab, setTab] as const;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm muted py-6">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-gray-300 border-t-accent-600" />
      {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-8 text-center text-sm muted">{children}</div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>;
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/30 p-6 overflow-auto" onClick={onClose}>
      <div className={`card w-full ${wide ? "max-w-5xl" : "max-w-2xl"} mt-8 shadow-xl`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
          <h2>{title}</h2>
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
        <div className="p-4 max-h-[75vh] overflow-auto">{children}</div>
      </div>
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs">{children}</span>;
}

export const usd = (v?: number | null, digits = 0) =>
  v === undefined || v === null ? "—" : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: digits })}`;

export const usdShort = (v?: number | null) => {
  if (v === undefined || v === null) return "—";
  const a = Math.abs(v);
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(0)}k`;
  return `$${v.toFixed(0)}`;
};

export const pct = (v?: number | null) => (v === undefined || v === null ? "—" : `${Math.round(v * 100)}%`);

export function since(iso?: string | null) {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="inline-flex items-center gap-2 text-xs muted cursor-pointer select-none">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-accent-600" />
      {label}
    </label>
  );
}
