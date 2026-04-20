"use client";

import { ensureDemoSession } from "@/lib/authSession";
import { useEffect, useMemo, useState } from "react";

type CaseRow = {
  case_id: string;
  title: string;
  description: string;
  status: string;
  finalized_at?: string | null;
  linked_executions?: string[];
};

export default function CasesPage() {
  const [sess, setSess] = useState<{ accessToken: string; orgId: string } | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [pending, setPending] = useState(false);
  const [title, setTitle] = useState("EU AI Act compliance review — Hiring tool");
  const [description, setDescription] = useState("Assess compliance before deployment. Collect evidence, cite regulations/controls, produce a decision.");
  const [template, setTemplate] = useState<"EU_AI_ACT" | "GDPR" | "SOC2" | "ISO27001">("EU_AI_ACT");

  const headers = useMemo(() => {
    const h: Record<string, string> = {};
    if (!sess) return h;
    h["Authorization"] = `Bearer ${sess.accessToken}`;
    h["X-Org-Id"] = sess.orgId;
    return h;
  }, [sess]);

  async function load() {
    if (!sess) return;
    const res = await fetch("/api/cases", { headers, cache: "no-store" });
    const body = (await res.json()) as { cases?: any[] };
    setCases((body.cases || []) as CaseRow[]);
  }

  useEffect(() => {
    (async () => {
      const s = await ensureDemoSession();
      setSess(s);
    })();
  }, []);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sess?.orgId]);

  async function createCase() {
    if (!sess) return;
    setPending(true);
    try {
      const res = await fetch("/api/cases", {
        method: "POST",
        headers: { "content-type": "application/json", ...headers },
        body: JSON.stringify({ title, description }),
      });
      const body = (await res.json()) as { case_id?: string };
      if (body.case_id) window.location.href = `/cases/${body.case_id}`;
      else await load();
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-r from-indigo-500/10 via-cyan-500/10 to-emerald-500/10 p-6 ring-1 ring-white/5">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Compliance Cases</h1>
          <div className="flex items-center gap-3 text-sm">
            <a className="text-slate-200 underline decoration-indigo-400/50 hover:text-white" href="/">
              Executions
            </a>
            <a className="text-slate-200 underline decoration-cyan-400/50 hover:text-white" href="/marketplace">
              Marketplace
            </a>
          </div>
        </div>
        <p className="mt-2 text-slate-200/90">Create and manage cases. Each case produces an explicit decision with citations and an export pack.</p>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5">
        <div className="grid gap-3">
          <label className="grid gap-1">
            <span className="text-xs text-slate-300/80">Template</span>
            <select
              className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100"
              value={template}
              onChange={(e) => {
                const v = e.target.value as any;
                setTemplate(v);
                if (v === "EU_AI_ACT") setTitle("EU AI Act compliance review — Hiring tool");
                if (v === "GDPR") setTitle("GDPR compliance review — Hiring tool");
                if (v === "SOC2") setTitle("SOC 2 readiness review — Core platform");
                if (v === "ISO27001") setTitle("ISO 27001 controls review — ISMS scope");
              }}
            >
              <option value="EU_AI_ACT">EU AI Act</option>
              <option value="GDPR">GDPR</option>
              <option value="SOC2">SOC 2</option>
              <option value="ISO27001">ISO 27001</option>
            </select>
          </label>
          <label className="grid gap-1">
            <span className="text-xs text-slate-300/80">Title</span>
            <input
              className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="grid gap-1">
            <span className="text-xs text-slate-300/80">Description</span>
            <textarea
              className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={pending || !sess}
              onClick={createCase}
              className="rounded-xl bg-gradient-to-r from-indigo-600 via-cyan-600 to-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-900/20 hover:from-indigo-500 hover:via-cyan-500 hover:to-emerald-500 disabled:opacity-60"
            >
              {pending ? "Creating…" : "Create case"}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-3">
        {cases.length ? (
          cases.map((c) => (
            <a
              key={c.case_id}
              href={`/cases/${c.case_id}`}
              className="block rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5 hover:bg-slate-900/50"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate text-lg font-semibold text-slate-50">{c.title}</div>
                  {c.description ? <div className="mt-1 text-sm text-slate-200/90">{c.description}</div> : null}
                  <div className="mt-2 text-xs text-slate-300/80">
                    status <span className="text-slate-100">{c.status}</span> · executions{" "}
                    <span className="text-slate-100">{(c.linked_executions || []).length}</span>
                  </div>
                </div>
              </div>
            </a>
          ))
        ) : (
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/35 p-6 text-slate-200 ring-1 ring-white/5">
            No cases yet. Create one above.
          </div>
        )}
      </div>
    </main>
  );
}

