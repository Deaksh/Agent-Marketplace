"use client";

import { ensureDefaultOrgId } from "@/lib/defaultOrg";
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
  agent_package_id?: string | null;
  agent_version_id?: string | null;
  agent_package?: { id: string; publisher: string; slug: string; name: string } | null;
  agent_version?: { id: string; version: string; runtime: string; builtin_agent_name?: string | null } | null;
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

type PersonaField = {
  key: string;
  label: string;
  type: "string" | "boolean" | "enum" | "string_list" | "text";
  required: boolean;
  placeholder?: string | null;
  options?: string[] | null;
  help?: string | null;
};

type PersonaDef = { key: string; label: string; goal: string; fields: PersonaField[] };
type PersonasResp = { personas: PersonaDef[] };

type Risk = { key?: string; severity?: string; description?: string; mitigation_hint?: string };
type Recommendation = { title?: string; why?: string; how?: string };
type Explainability = { checks?: { check?: string; ok?: boolean; [k: string]: unknown }[]; notes?: string[] };

function asArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

function severityColor(sev: string | undefined) {
  const s = (sev || "").toLowerCase();
  if (s === "high") return "border-red-900/60 bg-red-950/30 text-red-200";
  if (s === "medium") return "border-amber-900/60 bg-amber-950/30 text-amber-200";
  if (s === "low") return "border-emerald-900/60 bg-emerald-950/30 text-emerald-200";
  return "border-zinc-800 bg-zinc-950 text-zinc-200";
}

export function ExecutePanel() {
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<ExecFull | null>(null);
  const [steps, setSteps] = useState<StepsResp | null>(null);
  const [audit, setAudit] = useState<AuditResp | null>(null);
  const [personas, setPersonas] = useState<PersonaDef[]>([]);
  const [personaKey, setPersonaKey] = useState<string>("founder_pm");
  const [activeTab, setActiveTab] = useState<
    "summary" | "risks" | "recommendations" | "evidence" | "steps" | "audit" | "explainability" | "raw"
  >("summary");

  type ExecRow = {
    execution_id: string;
    created_at_ms: number;
    persona: string;
    intent: string;
    status?: string;
  };

  const [executions, setExecutions] = useState<ExecRow[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string>("");

  const pollUrl = useMemo(
    () => (selectedExecutionId ? `/api/executions/${selectedExecutionId}` : ""),
    [selectedExecutionId]
  );
  const stepsUrl = useMemo(
    () => (selectedExecutionId ? `/api/executions/${selectedExecutionId}/steps` : ""),
    [selectedExecutionId]
  );
  const auditUrl = useMemo(
    () => (selectedExecutionId ? `/api/executions/${selectedExecutionId}/audit` : ""),
    [selectedExecutionId]
  );

  const activePersona = useMemo(
    () => personas.find((p) => p.key === personaKey) || null,
    [personas, personaKey]
  );

  async function ensurePersonasLoaded() {
    if (personas.length) return;
    const res = await fetch("/api/personas", { cache: "no-store" });
    const body = (await res.json()) as PersonasResp;
    setPersonas(body.personas || []);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);

    const intent = String(formData.get("intent") || "");
    const region = String(formData.get("region") || "EU");
    const dataTypesRaw = String(formData.get("data_types") || "PII,biometric");
    const company = String(formData.get("company") || "");
    const dataRetention = String(formData.get("data_retention") || "");
    const dpiaDone = formData.get("dpia_done") ? true : false;

    const baseContext: Record<string, unknown> = {
      persona: personaKey,
      company: company || undefined,
      region,
      data_types: dataTypesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      data_retention: dataRetention || undefined,
      dpia_done: dpiaDone,
    };

    // Add persona-specific fields (best-effort; backend remains resilient).
    if (activePersona) {
      for (const f of activePersona.fields) {
        if (f.key in baseContext) continue; // already included common fields
        const raw = formData.get(f.key);
        if (f.type === "boolean") {
          baseContext[f.key] = raw ? true : false;
        } else if (f.type === "string_list") {
          const s = String(raw || "");
          baseContext[f.key] = s
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean);
        } else {
          const s = String(raw || "");
          baseContext[f.key] = s || undefined;
        }
      }
    }

    const context = baseContext;

    setPending(true);
    setResult(null);
    setSteps(null);
    setAudit(null);
    setActiveTab("summary");
    try {
      let orgId: string | undefined;
      try {
        orgId = await ensureDefaultOrgId();
      } catch {
        orgId = undefined;
      }
      const res = await fetch("/api/execute", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          orgId ? { intent, context, org_id: orgId } : { intent, context },
        ),
      });
      const body = (await res.json()) as ExecResp;
      const row: ExecRow = {
        execution_id: body.execution_id,
        created_at_ms: Date.now(),
        persona: personaKey,
        intent,
        status: body.status,
      };
      setExecutions((prev) => [row, ...prev].slice(0, 20));
      setSelectedExecutionId(body.execution_id);
      setDrawerOpen(true);
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

    // Update status in the list if present.
    try {
      const j = (await r1.clone().json()) as ExecFull;
      setExecutions((prev) =>
        prev.map((x) => (x.execution_id === j.execution_id ? { ...x, status: j.status } : x))
      );
    } catch {
      // ignore
    }
  }

  async function pollOnce() {
    if (!pollUrl) return;
    const res = await fetch(pollUrl, { cache: "no-store" });
    const body = (await res.json()) as ExecFull;
    setResult(body);
    setExecutions((prev) =>
      prev.map((x) => (x.execution_id === body.execution_id ? { ...x, status: body.status } : x))
    );
  }

  const evidenceSnippets = useMemo(() => {
    const trail = asArray<any>(result?.audit_trail);
    const rr = trail.find((s) => s?.agent === "regulation_retriever");
    return asArray<any>(rr?.output?.snippets);
  }, [result]);

  function openExecution(row: ExecRow) {
    setSelectedExecutionId(row.execution_id);
    setDrawerOpen(true);
    setResult(null);
    setSteps(null);
    setAudit(null);
    setActiveTab("summary");
  }

  return (
    <section className="mt-6 grid gap-6">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-lg font-semibold">Create execution</h2>
        <form
          onSubmit={onSubmit}
          onFocusCapture={() => {
            void ensurePersonasLoaded();
          }}
          className="mt-4 grid gap-3"
        >
          <label className="grid gap-1 text-sm">
            <span className="text-zinc-300">Persona</span>
            <select
              value={personaKey}
              onChange={(e) => setPersonaKey(e.target.value)}
              className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none"
            >
              {(personas.length ? personas : [{ key: "founder_pm", label: "Founder / PM", goal: "", fields: [] }]).map(
                (p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                )
              )}
            </select>
            {activePersona ? (
              <span className="text-xs text-zinc-500">{activePersona.goal}</span>
            ) : null}
          </label>
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

          {activePersona
            ? activePersona.fields
                .filter(
                  (f) =>
                    ![
                      "company",
                      "region",
                      "data_types",
                      "data_retention",
                      "dpia_done",
                      "persona",
                    ].includes(f.key)
                )
                .map((f) => {
                  const commonClass =
                    "rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 outline-none";
                  if (f.type === "boolean") {
                    return (
                      <label
                        key={f.key}
                        className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm"
                      >
                        <span className="text-zinc-300">{f.label}</span>
                        <input name={f.key} type="checkbox" className="h-4 w-4" />
                      </label>
                    );
                  }
                  if (f.type === "enum") {
                    return (
                      <label key={f.key} className="grid gap-1 text-sm">
                        <span className="text-zinc-300">{f.label}</span>
                        <select name={f.key} className={commonClass} defaultValue="">
                          <option value="">Select…</option>
                          {(f.options || []).map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                        {f.help ? <span className="text-xs text-zinc-500">{f.help}</span> : null}
                      </label>
                    );
                  }
                  const isText = f.type === "text";
                  return (
                    <label key={f.key} className="grid gap-1 text-sm">
                      <span className="text-zinc-300">{f.label}</span>
                      {isText ? (
                        <textarea
                          name={f.key}
                          placeholder={f.placeholder || undefined}
                          className={commonClass}
                          rows={3}
                        />
                      ) : (
                        <input
                          name={f.key}
                          placeholder={f.placeholder || undefined}
                          className={commonClass}
                        />
                      )}
                      {f.help ? <span className="text-xs text-zinc-500">{f.help}</span> : null}
                    </label>
                  );
                })
            : null}
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
        {executions.length ? (
          <div className="mt-6">
            <h3 className="text-sm font-semibold text-zinc-200">Executions</h3>
            <div className="mt-3 divide-y divide-zinc-800 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950">
              {executions.map((row) => (
                <button
                  key={row.execution_id}
                  type="button"
                  onClick={() => openExecution(row)}
                  className="w-full px-3 py-2 text-left hover:bg-zinc-900"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-zinc-100">{row.intent}</div>
                      <div className="mt-0.5 truncate text-[11px] text-zinc-400">
                        {row.persona} · {row.execution_id}
                      </div>
                    </div>
                    <div className="shrink-0 text-[11px] text-zinc-300">{row.status || "queued"}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {/* Right-side drawer */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-50">
          <button
            type="button"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 bg-black/60"
            aria-label="Close drawer"
          />
          <div className="absolute right-0 top-0 h-full w-full max-w-xl border-l border-zinc-800 bg-zinc-950 shadow-2xl">
            <div className="flex items-center justify-between gap-3 border-b border-zinc-800 p-4">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-zinc-100">Execution</div>
                <div className="mt-0.5 truncate text-[11px] text-zinc-400">{selectedExecutionId}</div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setDrawerOpen(false)}
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs hover:bg-zinc-800"
                >
                  Close
                </button>
              </div>
            </div>

            <div className="h-full overflow-auto p-4 pb-24 text-zinc-200">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={pollOnce}
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs hover:bg-zinc-800"
                >
                  Poll once
                </button>
                <button
                  type="button"
                  onClick={pollAllOnce}
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs hover:bg-zinc-800"
                >
                  Poll + steps + audit
                </button>
                <a
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs hover:bg-zinc-800"
                  href={pollUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open JSON
                </a>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {(
                  [
                    ["summary", "Summary"],
                    ["risks", "Risks"],
                    ["recommendations", "Recommendations"],
                    ["evidence", "Evidence"],
                    ["steps", "Steps"],
                    ["audit", "Audit"],
                    ["explainability", "Explainability"],
                    ["raw", "Raw"],
                  ] as const
                ).map(([k, label]) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setActiveTab(k)}
                    className={
                      "rounded-lg border px-3 py-1.5 text-xs " +
                      (activeTab === k
                        ? "border-indigo-500 bg-indigo-950/40 text-indigo-100"
                        : "border-zinc-700 bg-zinc-900 hover:bg-zinc-800")
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>

              {!result ? (
                <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                  Poll to load results.
                </div>
              ) : (
                <div className="mt-4">
                  {activeTab === "summary" ? (
                    <div className="grid gap-3">
                      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                        <div className="text-[11px] text-zinc-400">Status</div>
                        <div className="text-sm font-semibold text-zinc-100">{result.status}</div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                          <div className="text-[11px] text-zinc-400">Confidence</div>
                          <div className="text-sm font-semibold text-zinc-100">
                            {typeof result.confidence === "number" ? result.confidence.toFixed(2) : "—"}
                          </div>
                        </div>
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                          <div className="text-[11px] text-zinc-400">Execution</div>
                          <div className="text-sm font-semibold text-zinc-100">{result.execution_id}</div>
                        </div>
                      </div>
                      {result.result ? (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                          <div className="text-[11px] text-zinc-400">Report</div>
                          <pre className="mt-2 whitespace-pre-wrap text-[12px] leading-snug text-zinc-200">
                            {result.result}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {activeTab === "risks" ? (
                    <div className="grid gap-2">
                      {asArray<Risk>(result.risks).length ? (
                        asArray<Risk>(result.risks).map((r, idx) => (
                          <div key={idx} className={"rounded-xl border p-3 " + severityColor(r.severity)}>
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-xs font-semibold">{r.key || "risk"}</div>
                              <div className="text-[11px] opacity-80">{(r.severity || "unknown").toUpperCase()}</div>
                            </div>
                            <div className="mt-1 text-sm">{r.description}</div>
                            {r.mitigation_hint ? (
                              <div className="mt-2 text-[12px] text-zinc-300">
                                <span className="text-zinc-400">Mitigation:</span> {r.mitigation_hint}
                              </div>
                            ) : null}
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                          No risks reported.
                        </div>
                      )}
                    </div>
                  ) : null}

                  {activeTab === "recommendations" ? (
                    <div className="grid gap-2">
                      {asArray<Recommendation>(result.recommendations).length ? (
                        asArray<Recommendation>(result.recommendations).map((rec, idx) => (
                          <div key={idx} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                            <div className="text-sm font-semibold text-zinc-100">
                              {rec.title || "Recommendation"}
                            </div>
                            {rec.why ? <div className="mt-1 text-[12px] text-zinc-300">{rec.why}</div> : null}
                            {rec.how ? (
                              <div className="mt-2 text-[12px] text-zinc-300">
                                <span className="text-zinc-400">How:</span> {rec.how}
                              </div>
                            ) : null}
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                          No recommendations reported.
                        </div>
                      )}
                    </div>
                  ) : null}

                  {activeTab === "evidence" ? (
                    <div className="grid gap-2">
                      {!evidenceSnippets.length ? (
                        <div className="rounded-xl border border-amber-900/60 bg-amber-950/30 p-3 text-sm text-amber-200">
                          No evidence snippets were retrieved. If this is a fresh Codespace, seed regulations at{" "}
                          <code className="text-amber-100">/api/regulations/seed</code> and retry.
                        </div>
                      ) : (
                        <div className="grid gap-2">
                          {evidenceSnippets.map((s: any, idx: number) => (
                            <div key={idx} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="truncate text-sm font-semibold text-zinc-100">
                                    {s.unit_id} {s.title ? `— ${s.title}` : ""}
                                  </div>
                                  {s.version ? (
                                    <div className="text-[11px] text-zinc-500">v{String(s.version)}</div>
                                  ) : null}
                                </div>
                                <div className="shrink-0 text-[11px] text-zinc-400">
                                  {typeof s.score === "number" ? s.score.toFixed(2) : "—"}
                                </div>
                              </div>
                              {s.text ? (
                                <div className="mt-2 text-[12px] leading-snug text-zinc-300">{s.text}</div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : null}

                  {activeTab === "steps" ? (
                    <div className="grid gap-2">
                      {!steps ? (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                          Poll + steps + audit to load step details.
                        </div>
                      ) : steps.steps.length ? (
                        steps.steps.map((s) => (
                          <div key={s.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="text-sm font-semibold text-zinc-100">
                                  #{s.step_index} · {s.agent_name}
                                </div>
                                {s.agent_package && s.agent_version ? (
                                  <div className="mt-1 text-[12px] text-zinc-400">
                                    Marketplace: {s.agent_package.publisher} ·{" "}
                                    <span className="font-mono">{s.agent_package.slug}</span> · v{s.agent_version.version} ·{" "}
                                    {s.agent_version.runtime}
                                  </div>
                                ) : null}
                              </div>
                              <div className="shrink-0 text-right text-[11px] text-zinc-400">
                                <div className="text-zinc-200">{s.status}</div>
                                <div>attempts {s.attempts}</div>
                              </div>
                            </div>
                            {s.error ? <div className="mt-2 text-[12px] text-red-200">{s.error}</div> : null}
                            <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-zinc-400">
                              {s.started_at ? <span>start {s.started_at}</span> : null}
                              {s.completed_at ? <span>end {s.completed_at}</span> : null}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                          No steps yet.
                        </div>
                      )}
                    </div>
                  ) : null}

                  {activeTab === "audit" ? (
                    <div className="grid gap-2">
                      {!audit ? (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                          Poll + steps + audit to load audit events.
                        </div>
                      ) : audit.events.length ? (
                        audit.events.map((ev) => (
                          <div key={ev.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="text-xs font-semibold text-zinc-100">{ev.event_type}</div>
                                {ev.message ? <div className="mt-1 text-sm text-zinc-200">{ev.message}</div> : null}
                                {ev.step_id ? (
                                  <div className="mt-1 text-[11px] text-zinc-400">
                                    step_id <span className="font-mono">{ev.step_id}</span>
                                  </div>
                                ) : null}
                              </div>
                              <div className="shrink-0 text-[11px] text-zinc-400">{ev.created_at || ""}</div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                          No audit events yet.
                        </div>
                      )}
                    </div>
                  ) : null}

                  {activeTab === "explainability" ? (
                    <div className="grid gap-2">
                      {(() => {
                        const ex = (result.explainability || {}) as Explainability;
                        const checks = asArray<Explainability["checks"][number]>(ex.checks);
                        return (
                          <div className="grid gap-2">
                            {checks.length ? (
                              checks.map((c, idx) => (
                                <div
                                  key={idx}
                                  className={
                                    "rounded-xl border p-3 " +
                                    (c.ok
                                      ? "border-emerald-900/60 bg-emerald-950/30"
                                      : "border-rose-900/60 bg-rose-950/30")
                                  }
                                >
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-semibold text-zinc-100">{c.check || "check"}</div>
                                    <div className="text-[11px] text-zinc-300">{c.ok ? "OK" : "FAIL"}</div>
                                  </div>
                                  <pre className="mt-2 overflow-auto text-[11px] text-zinc-300">
                                    {JSON.stringify(c, null, 2)}
                                  </pre>
                                </div>
                              ))
                            ) : (
                              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                                No explainability checks reported.
                              </div>
                            )}
                            {asArray<string>(ex.notes).length ? (
                              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-sm text-zinc-300">
                                <div className="text-sm font-semibold text-zinc-100">Notes</div>
                                <ul className="mt-2 list-disc space-y-1 pl-5">
                                  {asArray<string>(ex.notes).map((n, i) => (
                                    <li key={i}>{n}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                        );
                      })()}
                    </div>
                  ) : null}

                  {activeTab === "raw" ? (
                    <div className="grid gap-2">
                      <details className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                        <summary className="cursor-pointer text-sm font-semibold text-zinc-100">
                          Execution JSON
                        </summary>
                        <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                          {JSON.stringify(result, null, 2)}
                        </pre>
                      </details>
                      {steps ? (
                        <details className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                          <summary className="cursor-pointer text-sm font-semibold text-zinc-100">Steps</summary>
                          <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                            {JSON.stringify(steps, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                      {audit ? (
                        <details className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
                          <summary className="cursor-pointer text-sm font-semibold text-zinc-100">Audit events</summary>
                          <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                            {JSON.stringify(audit, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

