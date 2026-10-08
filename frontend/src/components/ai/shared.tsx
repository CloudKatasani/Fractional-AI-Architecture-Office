import { ReactNode } from "react";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { Badge, TierBadge } from "../ui";

// Record-id prefixes that resolve via /records/{id} (mirrors GET /prefixes). Anything else (AIR-*, CTL-*) is a catalog id → badge.
const RECORD_PREFIXES = new Set([
  "APP", "INV", "CON", "SSO", "CLD", "CI", "API", "INT", "REPO", "INC", "PRJ", "DES", "STD", "PAT", "ADR", "DS", "PL", "BI",
  "POL", "AIU", "AIA", "DSC", "CAP", "DOC", "GOAL", "USR", "APR", "RUN", "TCK", "AUD",
]);

export function isRecordId(id?: string | null): boolean {
  if (!id) return false;
  const m = /^([A-Z]{2,5})-[A-Za-z0-9-]+$/.exec(id);
  return !!m && RECORD_PREFIXES.has(m[1]);
}

/** Evidence chip when the id is a source record, otherwise a mono badge. */
export function RefChip({ id, title }: { id: string; title?: string }) {
  if (isRecordId(id)) return <IdChip id={id} title={title} />;
  return (
    <span title={title} className="mr-1 mb-0.5 inline-flex shrink-0 items-center whitespace-nowrap rounded border border-gray-200 bg-gray-50 px-1 py-px font-mono text-[11px] text-gray-700">
      {id}
    </span>
  );
}

const TIER_COLOR: Record<string, string> = { unacceptable: "red", high: "red", limited: "amber", minimal: "green" };

/** Risk rule id like AIR-H4, colored by the tier it triggers. */
export function RuleBadge({ ruleId, tier, title }: { ruleId: string; tier?: string; title?: string }) {
  return (
    <Badge color={TIER_COLOR[tier || ""] || "gray"} title={title}>
      <span className="font-mono">{ruleId}</span>
    </Badge>
  );
}

export function downloadBlob(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export interface Trigger { rule_id: string; title: string; tier: string; reason: string; reference?: string; regulation?: string }
export interface Control { id: string; title: string; source: string; source_text?: string }

export function TriggerList({ triggers, compact }: { triggers?: Trigger[] | null; compact?: boolean }) {
  if (!triggers || triggers.length === 0) return <span className="text-xs muted">—</span>;
  if (compact)
    return (
      <span className="inline-flex flex-wrap gap-1">
        {triggers.map((t) => (
          <RuleBadge key={t.rule_id} ruleId={t.rule_id} tier={t.tier} title={`${t.title} — ${t.reason}`} />
        ))}
      </span>
    );
  return (
    <ul className="space-y-2">
      {triggers.map((t) => (
        <li key={t.rule_id} className="text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <RuleBadge ruleId={t.rule_id} tier={t.tier} />
            <span className="font-medium text-gray-900">{t.title}</span>
            <TierBadge tier={t.tier} />
          </div>
          <div className="mt-0.5 pl-1 text-xs text-gray-600">
            Matched because <span className="font-mono">{t.reason}</span>
            {t.regulation && <> · {t.regulation}</>}
            {t.reference && <> · <span className="italic">{t.reference}</span></>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ControlsChecklist({ controls, max }: { controls?: Control[] | null; max?: number }) {
  if (!controls || controls.length === 0) return <span className="text-xs muted">—</span>;
  const shown = max ? controls.slice(0, max) : controls;
  return (
    <ul className="space-y-0.5">
      {shown.map((c) => (
        <li key={c.id + c.source} className="flex items-start gap-1.5 text-xs" title={c.source_text}>
          <span className="mt-0.5 inline-block h-3 w-3 shrink-0 rounded-sm border border-gray-400 bg-white" />
          <span className="shrink-0 whitespace-nowrap font-mono text-gray-500">{c.id}</span>
          <span className="flex-1 text-gray-800">{c.title}</span>
          <RefChip id={c.source} title={c.source_text} />
        </li>
      ))}
      {max && controls.length > max && <li className="text-[11px] muted pl-4">+{controls.length - max} more</li>}
    </ul>
  );
}

export function DocChecklist({ items }: { items?: string[] | null }) {
  if (!items || items.length === 0) return <span className="text-xs muted">—</span>;
  return (
    <ul className="grid gap-0.5 sm:grid-cols-2">
      {items.map((d) => (
        <li key={d} className="flex items-center gap-1.5 text-xs">
          <span className="inline-block h-3 w-3 shrink-0 rounded-sm border border-gray-400 bg-white" />
          {d}
        </li>
      ))}
    </ul>
  );
}

export function BlockedBanner({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
      <span className="rounded bg-red-600 px-1.5 py-0.5 text-[11px] font-bold tracking-wide text-white">BLOCKED</span>
      <div>{children}</div>
    </div>
  );
}

/** Full rendering of a RiskClassification finding. */
export function RiskResult({ risk }: { risk: any }) {
  if (!risk) return null;
  const blocked = risk.blocked || risk.tier === "unacceptable";
  return (
    <div className="space-y-3">
      {blocked && (
        <BlockedBanner>
          <b>{risk.title || risk.usecase_id}</b> is a prohibited practice and may not proceed. Only a refusal record is required.
        </BlockedBanner>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="label">Proposed tier</span>
        <span className="text-base">
          <TierBadge tier={risk.tier} />
        </span>
        {risk.run_id && <EvidenceChip id={risk.run_id} />}
        <EvidenceList refs={risk.source_refs} />
      </div>
      <div>
        <div className="label mb-1">Triggers (rule ids)</div>
        <TriggerList triggers={risk.triggers} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="label mb-1">Required controls ({risk.required_controls?.length || 0})</div>
          <ControlsChecklist controls={risk.required_controls} />
        </div>
        <div>
          <div className="label mb-1">Documentation checklist</div>
          <DocChecklist items={risk.documentation_checklist} />
        </div>
      </div>
    </div>
  );
}

export const FLAG_LABELS: Record<string, { label: string; color: string; title: string }> = {
  unregistered: { label: "unregistered", color: "red", title: "Not in the model / agent registry (shadow AI)" },
  no_eval: { label: "no eval", color: "amber", title: "No evaluation on record" },
  expense_paid: { label: "expense-paid", color: "purple", title: "Paid through expense reports, not AP" },
  unapproved_vendor: { label: "unapproved vendor", color: "red", title: "Vendor not on the approved GenAI platform list" },
  production_without_eval: { label: "prod without eval", color: "red", title: "In production without a completed evaluation" },
  unknown_data: { label: "unknown data", color: "amber", title: "Data used is not declared" },
};

export function FlagBadge({ flag }: { flag: string }) {
  const f = FLAG_LABELS[flag] || { label: flag.replace(/_/g, " "), color: "gray", title: flag };
  return <Badge color={f.color} title={f.title}>{f.label}</Badge>;
}

export function ScoreBar({ value, max = 5, color = "bg-accent-500" }: { value?: number | null; max?: number; color?: string }) {
  if (value === undefined || value === null) return <span className="muted text-xs">—</span>;
  const w = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-1.5 w-14 overflow-hidden rounded bg-gray-100">
        <span className={`block h-full ${color}`} style={{ width: `${w}%` }} />
      </span>
      <span className="tabular-nums text-xs">{max === 1 ? `${Math.round(value * 100)}%` : value.toFixed(2)}</span>
    </span>
  );
}

/** EvidenceChip that never breaks across lines inside flex rows / narrow cells. */
export function IdChip({ id, label, title }: { id: string; label?: string; title?: string | null }) {
  return (
    <span className="inline-block shrink-0 whitespace-nowrap">
      <EvidenceChip id={id} label={label} title={title} />
    </span>
  );
}

/** Rough minimum render width for a Mermaid flowchart so big graphs scroll instead of shrinking to unreadable. */
export function mermaidMinWidth(chart?: string | null): number | undefined {
  if (!chart) return undefined;
  const lines = chart.split("\n").length;
  return lines > 30 ? Math.min(2600, lines * 14) : undefined;
}
