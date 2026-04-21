"use client";

import { ensureDemoSession } from "@/lib/authSession";
import { useEffect, useMemo, useState } from "react";

type CaseResp = {
  case_id: string;
  title: string;
  description: string;
  status: string;
  final_decision?: any;
  linked_executions: string[];
  system_name?: string;
  system_description?: string;
  use_case_type?: string;
  deployment_region?: string;
  data_types?: string[];
};

type ExecResp = {
  execution_id: string;
  status: string;
  decision?: string | null;
  severity?: string | null;
  blocking_issues?: any[] | null;
  required_actions?: any[] | null;
  citations?: any[] | null;
  result?: string | null;
  confidence?: number | null;
  risks?: any[] | null;
  recommendations?: any[] | null;
  audit_trail?: any[] | null;
  explainability?: any | null;
};

type StepRow = {
  id: string;
  step_index: number;
  agent_name: string;
  status: string;
  attempts: number;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  agent_package?: { publisher: string; slug: string; name: string } | null;
  agent_version?: { version: string; runtime: string } | null;
};
type StepsResp = { execution_id: string; steps: StepRow[] };

type AuditEvent = {
  id: string;
  step_id?: string | null;
  event_type: string;
  message: string;
  created_at?: string | null;
  payload?: any;
};
type AuditResp = { execution_id: string; events: AuditEvent[] };

const tabs = ["summary", "decision", "risks", "actions", "evidence", "steps", "audit"] as const;
type Tab = (typeof tabs)[number];

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const [sess, setSess] = useState<{ accessToken: string; orgId: string } | null>(null);
  const [caseData, setCaseData] = useState<CaseResp | null>(null);
  const [execs, setExecs] = useState<ExecResp[]>([]);
  const [steps, setSteps] = useState<StepsResp | null>(null);
  const [audit, setAudit] = useState<AuditResp | null>(null);
  const [active, setActive] = useState<Tab>("summary");
  const [pending, setPending] = useState(false);
  const [intent] = useState<string>("");

  const headers = useMemo(() => {
    const h: Record<string, string> = {};
    if (!sess) return h;
    h["Authorization"] = `Bearer ${sess.accessToken}`;
    h["X-Org-Id"] = sess.orgId;
    return h;
  }, [sess]);

  useEffect(() => {
    (async () => setSess(await ensureDemoSession()))();
  }, []);

  async function load() {
    const { id } = await params;
    if (!sess) return;
    const res = await fetch(`/api/cases/${id}`, { headers, cache: "no-store" });
    const body = (await res.json()) as CaseResp;
    setCaseData(body);
    const ids = body.linked_executions || [];
    const full: ExecResp[] = [];
    for (const eid of ids.slice(0, 10)) {
      const r = await fetch(`/api/executions/${eid}`, { headers, cache: "no-store" });
      full.push((await r.json()) as ExecResp);
    }
    setExecs(full);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sess?.orgId]);

  const latest = execs[0] || null;

  useEffect(() => {
    (async () => {
      if (!latest?.execution_id) return;
      try {
        const s = await fetch(`/api/executions/${latest.execution_id}/steps`, { cache: "no-store" });
        setSteps((await s.json()) as StepsResp);
      } catch {
        setSteps(null);
      }
      try {
        const a = await fetch(`/api/executions/${latest.execution_id}/audit`, { cache: "no-store" });
        setAudit((await a.json()) as AuditResp);
      } catch {
        setAudit(null);
      }
    })();
  }, [latest?.execution_id]);

  async function runExecution() {
    const { id } = await params;
    if (!sess) return;
    setPending(true);
    try {
      const res = await fetch(`/api/cases/${id}/execute`, {
        method: "POST",
        headers: { "content-type": "application/json", ...headers },
        body: JSON.stringify({ context: {} }),
      });
      await res.json();
      await load();
    } finally {
      setPending(false);
    }
  }

  async function exportPdf() {
    const { id } = await params;
    if (!sess) return;
    // Use same-origin proxy so the browser can render PDF reliably in Codespaces.
    const res = await fetch(`/api/cases/${id}/export?format=pdf`, { headers, cache: "no-store" });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-r from-fuchsia-500/10 via-indigo-500/10 to-cyan-500/10 p-6 ring-1 ring-white/5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold">{caseData?.title || "Case"}</h1>
            <div className="mt-1 text-sm text-slate-300/80">status {caseData?.status || "—"}</div>
            {caseData?.description ? <div className="mt-2 text-sm text-slate-200/90">{caseData.description}</div> : null}
          </div>
          <div className="flex items-center gap-2">
            <a className="text-sm text-slate-200 underline decoration-cyan-400/50 hover:text-white" href="/cases">
              Back
            </a>
            <button
              type="button"
              onClick={exportPdf}
              disabled={!sess}
              className="rounded-xl border border-slate-700/80 bg-slate-900/60 px-3 py-2 text-sm text-slate-100 hover:bg-slate-900/80 disabled:opacity-60"
            >
              Export PDF
            </button>
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="md:col-span-4 grid gap-2 rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
            <div className="text-xs text-slate-300/80">Intake</div>
            <div className="grid gap-1 text-sm text-slate-200 md:grid-cols-2">
              <div>
                System: <span className="text-slate-50 font-semibold">{caseData?.system_name || "—"}</span>
              </div>
              <div>
                Type: <span className="text-slate-50 font-semibold">{caseData?.use_case_type || "—"}</span>
              </div>
              <div>
                Region: <span className="text-slate-50 font-semibold">{caseData?.deployment_region || "—"}</span>
              </div>
              <div>
                Data: <span className="text-slate-50 font-semibold">{(caseData?.data_types || []).join(", ") || "—"}</span>
              </div>
            </div>
          </div>
          <div className="md:col-span-4 flex justify-end">
            <button
              type="button"
              disabled={pending || !sess}
              onClick={runExecution}
              className="rounded-xl bg-gradient-to-r from-indigo-600 via-cyan-600 to-fuchsia-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-900/20 hover:from-indigo-500 hover:via-cyan-500 hover:to-fuchsia-500 disabled:opacity-60"
            >
              {pending ? "Running…" : "Run execution"}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setActive(t)}
            className={
              "rounded-lg border px-3 py-1.5 text-xs " +
              (active === t
                ? "border-indigo-400/60 bg-indigo-500/10 text-indigo-100"
                : "border-slate-700/80 bg-slate-900/60 text-slate-100 hover:bg-slate-900/80")
            }
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5">
        {!latest ? (
          <div className="text-slate-200">No executions yet.</div>
        ) : active === "summary" ? (
          <div className="grid gap-3">
            <div className="text-sm text-slate-200">
              Latest execution: <span className="font-mono text-slate-100">{latest.execution_id}</span> ·{" "}
              <span className="text-slate-100">{latest.status}</span>
            </div>
            {latest.result ? <pre className="whitespace-pre-wrap text-[12px] text-slate-100/90">{latest.result}</pre> : null}
          </div>
        ) : active === "decision" ? (
          <div className="grid gap-2 text-sm text-slate-200">
            <div>
              Decision: <span className="text-slate-50 font-semibold">{latest.decision || "—"}</span>
            </div>
            <div>
              Severity: <span className="text-slate-50 font-semibold">{latest.severity || "—"}</span>
            </div>
            <div>
              Confidence: <span className="text-slate-50 font-semibold">{typeof latest.confidence === "number" ? latest.confidence.toFixed(2) : "—"}</span>
            </div>
          </div>
        ) : active === "risks" ? (
          <div className="grid gap-2">
            {(latest.risks || []).map((r, idx) => (
              <div key={idx} className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3 text-sm text-slate-200">
                <div className="font-semibold text-slate-100">{r.description || r.key || "risk"}</div>
                {r.severity ? <div className="mt-1 text-xs text-slate-300/80">severity {r.severity}</div> : null}
              </div>
            ))}
          </div>
        ) : active === "actions" ? (
          <div className="grid gap-2">
            {(latest.required_actions || []).map((a, idx) => (
              <div key={idx} className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3 text-sm text-slate-200">
                <div className="font-semibold text-slate-100">{a.title || "action"}</div>
                {a.why ? <div className="mt-1 text-xs text-slate-300/80">{a.why}</div> : null}
                {a.how ? <div className="mt-2 text-xs text-slate-200/90">How: {a.how}</div> : null}
              </div>
            ))}
          </div>
        ) : active === "evidence" ? (
          <div className="grid gap-2">
            {(latest.citations || []).map((c, idx) => (
              <div key={idx} className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3 text-sm text-slate-200">
                <div className="font-semibold text-slate-100">
                  {c.regulation_code} {c.unit_id} {c.title ? `— ${c.title}` : ""}
                </div>
                {c.snippet ? <div className="mt-2 text-xs text-slate-200/90">{String(c.snippet)}</div> : null}
              </div>
            ))}
          </div>
        ) : active === "steps" ? (
          <div className="grid gap-2">
            {steps?.steps?.length ? (
              steps.steps.map((s) => (
                <div key={s.id} className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3 text-sm text-slate-200">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="font-semibold text-slate-100">
                        {s.step_index}. {s.agent_name}
                      </div>
                      <div className="mt-1 text-xs text-slate-300/80">
                        status <span className="text-slate-100">{s.status}</span> · attempts{" "}
                        <span className="text-slate-100">{s.attempts}</span>
                        {s.started_at ? ` · start ${s.started_at}` : ""}
                        {s.completed_at ? ` · end ${s.completed_at}` : ""}
                      </div>
                      {s.agent_package ? (
                        <div className="mt-2 text-xs text-slate-300/80">
                          agent package: <span className="text-slate-100">{s.agent_package.publisher}</span> /{" "}
                          <span className="text-slate-100">{s.agent_package.slug}</span>
                          {s.agent_version ? (
                            <>
                              {" "}
                              · v<span className="text-slate-100">{s.agent_version.version}</span> ·{" "}
                              <span className="text-slate-100">{s.agent_version.runtime}</span>
                            </>
                          ) : null}
                        </div>
                      ) : null}
                      {s.error ? <div className="mt-2 text-xs text-rose-200">Error: {s.error}</div> : null}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-sm text-slate-200">No steps loaded yet.</div>
            )}
          </div>
        ) : (
          <div className="grid gap-2">
            {audit?.events?.length ? (
              audit.events.map((e) => (
                <div key={e.id} className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3 text-sm text-slate-200">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-xs text-slate-300/80">{e.created_at || ""}</div>
                      <div className="mt-1 font-semibold text-slate-100">{e.event_type}</div>
                      {e.message ? <div className="mt-1 text-sm text-slate-200/90">{e.message}</div> : null}
                      {e.step_id ? <div className="mt-1 text-xs text-slate-300/80">step_id {e.step_id}</div> : null}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-sm text-slate-200">No audit events loaded yet.</div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

