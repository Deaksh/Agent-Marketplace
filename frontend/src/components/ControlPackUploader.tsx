"use client";

import { ensureDemoSession } from "@/lib/authSession";
import { useState } from "react";

type Framework = "SOC2" | "ISO27001";

export function ControlPackUploader() {
  const [framework, setFramework] = useState<Framework>("SOC2");
  const [publisher, setPublisher] = useState("customer");
  const [sourceDocId, setSourceDocId] = useState("internal-mapping");
  const [unitsText, setUnitsText] = useState(
    JSON.stringify([{ unit_id: "CC7.2", title: "Monitoring for anomalies", text: "We monitor logs and alert on anomalies..." }], null, 2)
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");

  async function ingest() {
    setBusy(true);
    setMsg("");
    try {
      const sess = await ensureDemoSession();
      const units = JSON.parse(unitsText);
      const res = await fetch("/api/regulations/ingest/control_pack", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          Authorization: `Bearer ${sess.accessToken}`,
          "X-Org-Id": sess.orgId,
        },
        body: JSON.stringify({
          framework_code: framework,
          publisher,
          version: "uploaded-v1",
          source_doc_id: sourceDocId,
          jurisdiction: "GLOBAL",
          units,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || "Ingestion failed");
      setMsg(`Ingested: inserted=${body.inserted} updated=${body.updated} embedded=${body.embedded}`);
    } catch (e: any) {
      setMsg(`Error: ${e?.message || String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5">
      <div className="text-sm font-semibold text-slate-100">Upload SOC 2 / ISO control pack</div>
      <div className="mt-1 text-xs text-slate-300/80">
        Use this to ingest your own control mappings/summaries (licensing-safe). This will power retrieval + decisions.
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <label className="grid gap-1">
          <span className="text-xs text-slate-300/80">Framework</span>
          <select
            value={framework}
            onChange={(e) => setFramework(e.target.value as Framework)}
            className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100"
          >
            <option value="SOC2">SOC 2</option>
            <option value="ISO27001">ISO 27001</option>
          </select>
        </label>
        <label className="grid gap-1">
          <span className="text-xs text-slate-300/80">Publisher</span>
          <input
            value={publisher}
            onChange={(e) => setPublisher(e.target.value)}
            className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100"
          />
        </label>
        <label className="grid gap-1">
          <span className="text-xs text-slate-300/80">Source doc id</span>
          <input
            value={sourceDocId}
            onChange={(e) => setSourceDocId(e.target.value)}
            className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100"
          />
        </label>
      </div>

      <label className="mt-3 grid gap-1">
        <span className="text-xs text-slate-300/80">Units JSON</span>
        <textarea
          value={unitsText}
          onChange={(e) => setUnitsText(e.target.value)}
          rows={8}
          className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 font-mono text-[12px] text-slate-100"
        />
      </label>

      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="text-xs text-slate-300/80">{msg}</div>
        <button
          type="button"
          disabled={busy}
          onClick={ingest}
          className="rounded-xl bg-gradient-to-r from-indigo-600 via-cyan-600 to-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:from-indigo-500 hover:via-cyan-500 hover:to-emerald-500 disabled:opacity-60"
        >
          {busy ? "Uploading…" : "Ingest pack"}
        </button>
      </div>
    </div>
  );
}

