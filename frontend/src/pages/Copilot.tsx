import { FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { PageHeader } from "../components/Layout";
import { Markdown } from "../components/Markdown";
import { Mermaid } from "../components/Mermaid";
import { Badge, ErrorBox, Loading } from "../components/ui";
import { IdChip, mermaidMinWidth } from "../components/ai/shared";
import { useApi, useApp } from "../state/AppState";

interface Citation { id: string; type: string; name: string }
interface Answer { answer: string; citations: Citation[]; mermaid?: string | null; mode: string; duration_ms: number }
type Msg =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; data: Answer }
  | { role: "error"; content: string };

function AnswerCard({ a }: { a: Answer }) {
  const [showDiagram, setShowDiagram] = useState(true);
  return (
    <div className="card p-3 space-y-3" data-testid="copilot-answer">
      <div className="flex items-center gap-2 text-[11px] muted">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-accent-50 text-[10px] font-bold text-accent-700">AI</span>
        <span>Architecture Copilot</span>
        <Badge color={a.mode === "live" ? "purple" : "gray"}>{a.mode}</Badge>
        <span>{a.duration_ms} ms</span>
        <span>· {a.citations.length} citations</span>
      </div>
      <Markdown text={a.answer} />
      {a.mermaid && (
        <div className="rounded border border-gray-200 bg-white p-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="label">Diagram</span>
            <button className="text-[11px] text-accent-700 hover:underline" onClick={() => setShowDiagram((s) => !s)}>{showDiagram ? "hide" : "show"}</button>
          </div>
          {showDiagram && (
            <div className="max-h-[36rem] overflow-auto">
              <div style={{ minWidth: mermaidMinWidth(a.mermaid) }}>
                <Mermaid chart={a.mermaid} />
              </div>
            </div>
          )}
        </div>
      )}
      {a.citations.length > 0 && (
        <div>
          <div className="label mb-1">Sources</div>
          <ul className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
            {a.citations.map((c) => (
              <li key={c.id} className="flex min-w-0 items-center gap-1">
                <IdChip id={c.id} />
                <Badge>{c.type}</Badge>
                <span className="truncate text-gray-700" title={c.name}>{c.name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function Copilot() {
  const { user, tenant, tenantName } = useApp();
  const { data: suggestions, error: sugErr } = useApi<string[]>("/copilot/suggestions");
  const [params, setParams] = useSearchParams();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState(params.get("q") || "");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const autoAsked = useRef<string | null>(null);

  // conversation is per tenant
  useEffect(() => {
    setMsgs([]);
  }, [tenant]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const history = msgs
      .filter((m): m is Exclude<Msg, { role: "error" }> => m.role !== "error")
      .map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setBusy(true);
    try {
      const a = await api.post<Answer>("/copilot/ask", { question: q, history, user_id: user?.id });
      setMsgs((m) => [...m, { role: "assistant", content: a.answer, data: a }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "error", content: e.message || String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  // ?q= prefill + auto-ask (Graph Explorer "explain this node"); once per distinct q
  useEffect(() => {
    const q = params.get("q");
    if (!q || autoAsked.current === q) return;
    autoAsked.current = q;
    ask(q);
    const p = new URLSearchParams(params);
    p.delete("q");
    setParams(p, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    ask(input);
  };

  return (
    <div className="flex h-[calc(100vh-5.5rem)] flex-col">
      <PageHeader
        title="Copilot"
        subtitle={`Ask about ${tenantName}'s architecture — answers are grounded in the knowledge graph and cite source records.`}
        actions={msgs.length > 0 ? <button className="btn btn-sm" onClick={() => setMsgs([])} disabled={busy}>New conversation</button> : undefined}
      />
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1fr_18rem]">
        <div className="flex min-h-0 flex-col">
          <div className="min-h-0 flex-1 space-y-3 overflow-auto pr-1" data-testid="copilot-thread">
            {msgs.length === 0 && !busy && (
              <div className="card p-5">
                <div className="text-sm text-gray-700">Start with a suggested question or type your own. Every fact in an answer carries an evidence chip you can open.</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(suggestions || []).slice(0, 6).map((s) => (
                    <button key={s} className="rounded-full border border-accent-100 bg-accent-50 px-3 py-1 text-xs text-accent-700 hover:border-accent-500" onClick={() => ask(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[80%] rounded-lg bg-accent-600 px-3 py-2 text-sm text-white">{m.content}</div>
                </div>
              ) : m.role === "assistant" ? (
                <AnswerCard key={i} a={m.data} />
              ) : (
                <ErrorBox key={i} error={m.content} />
              ),
            )}
            {busy && <Loading label="Searching the knowledge graph…" />}
            <div ref={endRef} />
          </div>
          <form onSubmit={submit} className="mt-3 flex gap-2">
            <input
              className="input flex-1"
              placeholder="e.g. Who owns meter data and what AI uses it?"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
              data-testid="copilot-input"
            />
            <button className="btn-primary" type="submit" disabled={busy || !input.trim()} data-testid="copilot-send">
              {busy ? "Thinking…" : "Send"}
            </button>
          </form>
        </div>
        <aside className="card hidden min-h-0 overflow-auto p-3 lg:block">
          <div className="label mb-2">Suggested questions</div>
          <ErrorBox error={sugErr} />
          <div className="flex flex-col gap-1.5">
            {(suggestions || []).map((s) => (
              <button
                key={s}
                disabled={busy}
                onClick={() => ask(s)}
                className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-left text-xs text-gray-700 hover:border-accent-500 hover:bg-accent-50 disabled:opacity-50"
                data-testid="copilot-suggestion"
              >
                {s}
              </button>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
