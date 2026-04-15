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

export function ExecutePanel() {
  const [pending, setPending] = useState(false);
  const [lastExecutionId, setLastExecutionId] = useState<string>("");
  const [result, setResult] = useState<ExecFull | null>(null);

  const pollUrl = useMemo(
    () => (lastExecutionId ? `/api/executions/${lastExecutionId}` : ""),
    [lastExecutionId]
  );

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);

    const intent = String(formData.get("intent") || "");
    const region = String(formData.get("region") || "EU");
    const dataTypesRaw = String(formData.get("data_types") || "PII,biometric");
    const company = String(formData.get("company") || "");

    const context = {
      company: company || undefined,
      region,
      data_types: dataTypesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      dpia_done: false,
    };

    setPending(true);
    setResult(null);
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
        </ol>
      </div>
    </section>
  );
}

