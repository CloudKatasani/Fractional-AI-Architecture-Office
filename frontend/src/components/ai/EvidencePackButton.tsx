import { useState } from "react";
import { api } from "../../api/client";
import { useApi, useApp } from "../../state/AppState";
import { Markdown } from "../Markdown";
import { Badge, ErrorBox, Loading, Modal } from "../ui";
import { EvidenceChip } from "../Evidence";
import { downloadBlob, slug } from "./shared";

interface Regs {
  regulations: string[];
  policies: { id: string; title: string; regulation: string }[];
}

/** "Generate evidence pack" — pick a regulation or policy, POST /evidence/pack, show markdown with downloads. */
export function EvidencePackButton({ defaultId }: { defaultId?: string }) {
  const { user, tenant, refresh } = useApp();
  const [open, setOpen] = useState(false);
  const { data: regs, error: regErr } = useApi<Regs>(open ? "/evidence/regulations" : null);
  const [sel, setSel] = useState<string>(defaultId || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pack, setPack] = useState<any>(null);

  const choice = sel || regs?.regulations[0] || "";

  const generate = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post("/evidence/pack", { regulation_or_policy_id: choice, user_id: user?.id });
      setPack(r);
      refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const base = `evidence-pack-${tenant}-${slug(choice || "all")}`;
  const jsonText = () => {
    const j = pack?.json ?? pack;
    return typeof j === "string" ? j : JSON.stringify(j, null, 2);
  };

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)} data-testid="evidence-pack-btn">Generate evidence pack</button>
      <Modal open={open} onClose={() => { setOpen(false); setPack(null); }} title="Evidence pack" wide>
        <div className="space-y-3">
          <ErrorBox error={regErr} />
          {!regs && !regErr && <Loading />}
          {regs && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1">
                <span className="label">Regulation or policy</span>
                <select className="input min-w-[22rem]" value={choice} onChange={(e) => { setSel(e.target.value); setPack(null); }}>
                  <optgroup label="Regulations">
                    {regs.regulations.map((r) => <option key={r} value={r}>{r}</option>)}
                  </optgroup>
                  <optgroup label="Policies">
                    {regs.policies.map((p) => <option key={p.id} value={p.id}>{p.id} · {p.title} ({p.regulation})</option>)}
                  </optgroup>
                </select>
              </label>
              <button className="btn-primary" onClick={generate} disabled={busy || !choice}>{busy ? "Generating…" : "Generate"}</button>
              {pack && (
                <>
                  <button className="btn" onClick={() => downloadBlob(jsonText(), `${base}.json`, "application/json")}>Download JSON</button>
                  <button className="btn" onClick={() => downloadBlob(pack.markdown || "", `${base}.md`, "text/markdown")}>Download markdown</button>
                </>
              )}
            </div>
          )}
          <ErrorBox error={err} />
          {busy && <Loading label="Collecting controls, findings and decisions…" />}
          {pack && (
            <div className="border-t border-gray-100 pt-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                {pack.run_id && <EvidenceChip id={pack.run_id} />}
                {pack.summary && <span className="text-gray-700">{pack.summary}</span>}
                {Array.isArray(pack.findings) && <Badge>{pack.findings.length} controls</Badge>}
              </div>
              <Markdown text={pack.markdown} />
            </div>
          )}
          {!pack && !busy && regs && (
            <div className="text-sm muted">
              The pack lists each control mapped to the selected regulation, its open findings, approved remediations and recorded decisions — each with source-record chips.
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
