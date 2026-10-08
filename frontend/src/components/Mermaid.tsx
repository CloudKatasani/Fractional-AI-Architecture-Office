import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose", flowchart: { htmlLabels: true, curve: "basis" } });
let counter = 0;

export function Mermaid({ chart, className = "" }: { chart?: string | null; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showSrc, setShowSrc] = useState(false);
  useEffect(() => {
    if (!chart || !ref.current) return;
    const id = `mmd-${++counter}`;
    let alive = true;
    mermaid
      .render(id, chart)
      .then(({ svg }) => {
        if (alive && ref.current) {
          ref.current.innerHTML = svg;
          setErr(null);
        }
      })
      .catch((e) => {
        if (alive) setErr(String(e?.message || e));
        document.getElementById(`d${id}`)?.remove();
      });
    return () => {
      alive = false;
    };
  }, [chart]);
  if (!chart) return null;
  return (
    <div className={className}>
      <div ref={ref} className="overflow-auto [&_svg]:max-w-full [&_svg]:h-auto" />
      {err && <div className="text-xs text-red-700">Diagram could not be rendered: {err.slice(0, 200)}</div>}
      <button className="mt-1 text-[11px] muted hover:text-gray-700" onClick={() => setShowSrc((s) => !s)}>
        {showSrc ? "hide" : "show"} Mermaid source
      </button>
      {showSrc && <pre className="mt-1 max-h-60 overflow-auto rounded bg-gray-50 border border-gray-200 p-2 text-[11px]">{chart}</pre>}
    </div>
  );
}
