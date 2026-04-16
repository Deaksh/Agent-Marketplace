"use client";

import { useMemo, useState } from "react";

type ExecResp = { execution_id: string; status: string };
type ExecFull = {
  execution_id: string;
  status: string;
  result?: string | null;
  confidence?: number | null;
  risks?: unknown[] | null;
  recommendations?: unknown[] | null;
  audit_trail?: unknown[] | null;
  explainability?: unknown | null;
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
};

type StepsResp = { execution_id: string; steps: StepRow[] };

type AuditEvent = {
  id: string;
  step_id?: string | null;
  event_type: string;
  message: string;
  payload: unknown;
  created_at?: string | null;
};
type AuditResp = { execution_id: string; events: AuditEvent[] };

export function ExecutePanel() {
  const [pending, setPending] = useState(false);
  const [lastExecutionId, setLastExecutionId] = useState<string>("");
  const [result, setResult] = useState<ExecFull | null>(null);
  const [steps, setSteps] = useState<StepsResp | null>(null);
  const [audit, setAudit] = useState<AuditResp | null>(null);

  const pollUrl = useMemo(
    () => (lastExecutionId ? `/api/executions/${lastExecutionId}` : ""),
    [lastExecutionId]
  );
  const stepsUrl = useMemo(
    () => (lastExecutionId ? `/api/executions/${lastExecutionId}/steps` : ""),
    [lastExecutionId]
  );
  const auditUrl = useMemo(
    () => (lastExecutionId ? `/api/executions/${lastExecutionId}/audit` : ""),
    [lastExecutionId]
  );

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);

    const intent = String(formData.get("intent") || "");
    const region = String(formData.get("region") || "EU");
    const dataTypesRaw = String(formData.get("data_types") || "PII,biometric");
    const company = String(formData.get("company") || "");
    const dataRetention = String(formData.get("data_retention") || "");
    const dpiaDone = formData.get("dpia_done") ? true : false;

    const context = {
      company: company || undefined,
      region,
      data_types: dataTypesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      data_retention: dataRetention || undefined,
      dpia_done: dpiaDone,
    };

    setPending(true);
    setResult(null);
    setSteps(null);
    setAudit(null);
    try {
      const res = await fetch("/api/execute", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ intent, context }),
      });
      const body = (await res.json()) as ExecResp;
      setLastExecutionId(body.execution_id);
    } finally {
      setPending(false);
    }
  }

  async function pollAllOnce() {
    if (!pollUrl) return;
    const [r1, r2, r3] = await Promise.all([
      fetch(pollUrl, { cache: "no-store" }),
      stepsUrl ? fetch(stepsUrl, { cache: "no-store" }) : Promise.resolve(null),
      auditUrl ? fetch(auditUrl, { cache: "no-store" }) : Promise.resolve(null),
    ]);
    setResult((await r1.json()) as ExecFull);
    if (r2) setSteps((await r2.json()) as StepsResp);
    if (r3) setAudit((await r3.json()) as AuditResp);
  }

  async function pollOnce() {
    if (!pollUrl) return;
    const res = await fetch(pollUrl, { cache: "no-store" });
    const body = (await res.json()) as ExecFull;
    setResult(body);
  }

  return (
    <section className="mt-6 grid gap-6 md:grid-cols-2">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-lg font-semibold">Create execution</h2>
        <form onSubmit={onSubmit} className="mt-4 grid gap-3">
          <label className="grid gap-1 text-sm">
            <span className="text-zinc-300">Intent</span>
            <input
              name="intent"
              defaultValue="Check if my AI hiring tool is GDPR compliant"
              className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1 text-sm">
              <span className="text-zinc-300">Region</span>
              <input
                name="region"
                defaultValue="EU"
                className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none"
              />
            </label>
            <label className="grid gap-1 text-sm">
              <span className="text-zinc-300">Company</span>
              <input
                name="company"
                placeholder="Acme Inc"
                className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none"
              />
            </label>
          </div>
          <label className="grid gap-1 text-sm">
            <span className="text-zinc-300">Data types (comma-separated)</span>
            <input
              name="data_types"
              defaultValue="PII,biometric"
              className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none"
            />
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-zinc-300">Data retention</span>
            <input
              name="data_retention"
              placeholder="e.g., 12 months"
              className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none"
            />
          </label>
          <label className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
            <span className="text-zinc-300">DPIA done</span>
            <input name="dpia_done" type="checkbox" className="h-4 w-4" />
          </label>
          <button
            type="submit"
            disabled={pending}
            className="mt-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? "Executing..." : "Execute"}
          </button>
        </form>
        <p className="mt-3 text-xs text-zinc-400">
          After creating an execution, poll{" "}
          <code className="text-zinc-200">/api/executions/&lt;id&gt;</code>.
        </p>
        {lastExecutionId ? (
          <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-300">
            <div>
              Execution id: <code className="text-zinc-100">{lastExecutionId}</code>
            </div>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={pollOnce}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 hover:bg-zinc-800"
              >
                Poll once
              </button>
              <button
                type="button"
                onClick={pollAllOnce}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 hover:bg-zinc-800"
              >
                Poll + steps + audit
              </button>
              <a
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 hover:bg-zinc-800"
                href={pollUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open JSON
              </a>
            </div>
            {result ? (
              <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                {JSON.stringify(result, null, 2)}
              </pre>
            ) : null}
            {steps ? (
              <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                {JSON.stringify(steps, null, 2)}
              </pre>
            ) : null}
            {audit ? (
              <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                {JSON.stringify(audit, null, 2)}
              </pre>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-lg font-semibold">How to view results</h2>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-zinc-300">
          <li>
            Start backend on <code className="text-zinc-100">:8040</code> and frontend on{" "}
            <code className="text-zinc-100">:5273</code>.
          </li>
          <li>
            POST to <code className="text-zinc-100">/api/execute</code> to get an{" "}
            <code className="text-zinc-100">execution_id</code>.
          </li>
          <li>
            GET <code className="text-zinc-100">/api/executions/&lt;execution_id&gt;</code>{" "}
            until status is <code className="text-zinc-100">succeeded</code>.
          </li>
          <li>
            (Optional) GET{" "}
            <code className="text-zinc-100">/api/executions/&lt;execution_id&gt;/steps</code> for
            step-by-step progress and{" "}
            <code className="text-zinc-100">/api/executions/&lt;execution_id&gt;/audit</code> for a
            durable audit event stream.
          </li>
        </ol>
      </div>
    </section>
  );
}

