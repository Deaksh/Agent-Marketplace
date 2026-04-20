"use client";

import { useState } from "react";

type ReembedResp = {
  scanned: number;
  updated: number;
  skipped_empty: number;
  embed_provider: string;
  model?: string | null;
  errors: { id: number | null; unit_id: string; error: string }[];
  warning?: string;
};

export function RegulationReembedPanel() {
  const [framework, setFramework] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReembedResp | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const params = new URLSearchParams();
      if (framework.trim()) params.set("framework_code", framework.trim().toUpperCase());
      const res = await fetch(`/api/regulations/ingest/reembed?${params.toString()}`, { method: "POST" });
      const data = (await res.json()) as ReembedResp & { detail?: string };
      if (!res.ok) {
        setErr(typeof data.detail === "string" ? data.detail : res.statusText);
        return;
      }
      setResult(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5">
      <h2 className="text-sm font-semibold text-slate-100">Re-embed regulation units</h2>
      <p className="mt-1 text-xs text-slate-400">
        After you set <code className="text-slate-300">HF_TOKEN</code> in a real <code className="text-slate-300">.env</code> file
        (repo root or <code className="text-slate-300">backend/.env</code>), restart the API and run this to refresh vectors for RAG.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="grid gap-1">
          <span className="text-xs text-slate-300/80">Framework (optional)</span>
          <select
            value={framework}
            onChange={(e) => setFramework(e.target.value)}
            className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500/60 focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="">All frameworks</option>
            <option value="GDPR">GDPR</option>
            <option value="EU_AI_ACT">EU AI Act</option>
            <option value="SOC2">SOC 2</option>
            <option value="ISO27001">ISO 27001</option>
          </select>
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={run}
          className="rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-violet-900/20 hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50"
        >
          {busy ? "Re-embedding…" : "Run re-embed"}
        </button>
      </div>
      {err ? <p className="mt-3 text-sm text-rose-300">{err}</p> : null}
      {result ? (
        <div className="mt-3 rounded-xl border border-slate-800/60 bg-slate-950/50 p-3 text-xs text-slate-300">
          <div className="grid gap-1 sm:grid-cols-2">
            <div>
              Provider: <span className="text-slate-100">{result.embed_provider}</span>
            </div>
            {result.model ? (
              <div>
                Model: <span className="text-slate-100">{result.model}</span>
              </div>
            ) : null}
            <div>
              Scanned: <span className="text-slate-100">{result.scanned}</span>
            </div>
            <div>
              Updated: <span className="text-slate-100">{result.updated}</span>
            </div>
            <div>
              Skipped (empty text): <span className="text-slate-100">{result.skipped_empty}</span>
            </div>
            <div>
              Errors: <span className="text-slate-100">{result.errors?.length ?? 0}</span>
            </div>
          </div>
          {result.warning ? <p className="mt-2 text-amber-200/90">{result.warning}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
