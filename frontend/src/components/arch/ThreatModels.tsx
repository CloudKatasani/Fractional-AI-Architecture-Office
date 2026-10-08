import { useState } from "react";
import { AgentOutput } from "../../api/client";
import { useApi } from "../../state/AppState";
import { AgentPanel } from "../AgentPanel";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { Badge, Card, Empty, Loading } from "../ui";
import { getUrlParam, setUrlParam } from "./common";

const LVL: Record<string, string> = { high: "red", medium: "amber", low: "gray" };
const STRIDE_ORDER = ["Spoofing", "Tampering", "Repudiation", "Information disclosure", "Denial of service", "Elevation of privilege"];

export function ThreatTable({ threats }: { threats?: any[] | null }) {
  if (!threats || threats.length === 0) return <Empty>No threats identified.</Empty>;
  const rows = [...threats].sort(
    (a, b) => (a.component || "").localeCompare(b.component || "") || STRIDE_ORDER.indexOf(a.stride_category) - STRIDE_ORDER.indexOf(b.stride_category),
  );
  return (
    <div className="overflow-auto">
      <table className="tbl">
        <thead>
          <tr><th>Component</th><th>STRIDE</th><th>Threat</th><th>Likelihood</th><th>Impact</th><th>Mitigation</th><th>Standard</th></tr>
        </thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={i}>
              <td className="font-medium whitespace-nowrap">{t.component}</td>
              <td><Badge color="purple">{t.stride_category}</Badge></td>
              <td className="text-xs">{t.description}</td>
              <td><Badge color={LVL[t.likelihood] || "gray"}>{t.likelihood}</Badge></td>
              <td><Badge color={LVL[t.impact] || "gray"}>{t.impact}</Badge></td>
              <td className="text-xs">{t.mitigation}</td>
              <td className="whitespace-nowrap">{t.standard_id ? <EvidenceChip id={t.standard_id} /> : <span className="muted text-xs">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ThreatModels() {
  const { data: list } = useApi<any>("/app/designs");
  const designs: any[] = list?.items || [];
  const [sel, setSel] = useState<string>(getUrlParam("design") || "");
  const id = sel || designs[0]?.id || "";
  const { data: d, loading } = useApi<any>(id ? `/app/designs/${id}` : null, undefined, [id]);
  const [out, setOut] = useState<Record<string, AgentOutput>>({});
  const tm: any = out[id] || d?.threat_model || null;
  const f = tm?.findings?.[0];
  const counts: Record<string, number> = {};
  (f?.threats || []).forEach((t: any) => (counts[t.stride_category] = (counts[t.stride_category] || 0) + 1));
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <label className="label">Design</label>
          <select
            className="input min-w-[24rem]"
            value={id}
            onChange={(e) => {
              setSel(e.target.value);
              setUrlParam("design", e.target.value);
            }}
          >
            {designs.map((x) => (
              <option key={x.id} value={x.id}>{x.id} — {x.title}</option>
            ))}
          </select>
          {d && <span className="text-xs muted">{d.team} · components: {(d.components || []).join(", ") || "—"}</span>}
        </div>
      </Card>
      {loading && !d && <Loading />}
      {id && (
        <AgentPanel
          agentId="app.threat_model_assistant"
          title={`STRIDE threat model — ${d?.title || id}`}
          run={tm}
          params={{ design_id: id }}
          onRan={(o) => setOut((m) => ({ ...m, [id]: o }))}
          runLabel={tm ? "Re-run threat model" : "Generate threat model"}
        >
          {f ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2 text-xs">
                {STRIDE_ORDER.map((s) => (
                  <Badge key={s} color={counts[s] ? "purple" : "gray"}>{s}: {counts[s] || 0}</Badge>
                ))}
              </div>
              {f.data_classifications?.length > 0 && (
                <div className="text-xs">
                  <span className="muted">Data classification in scope: </span>
                  {(f.data_classifications as string[]).map((c) => <Badge key={c} color={c === "restricted" || c === "confidential" ? "red" : "gray"}>{c}</Badge>)}
                </div>
              )}
              <ThreatTable threats={f.threats} />
              <div className="text-xs"><span className="muted">Evidence: </span><EvidenceList refs={f.source_refs} /></div>
            </div>
          ) : (
            <Empty>No threat model for this design yet — generate one.</Empty>
          )}
        </AgentPanel>
      )}
    </div>
  );
}
