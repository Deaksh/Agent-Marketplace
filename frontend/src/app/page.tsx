export default function Page() {
  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h1 className="text-2xl font-semibold">Outcome Execution Layer</h1>
        <p className="mt-2 text-zinc-300">
          API-first MVP for regulatory compliance workflows. This UI is a thin client
          for creating executions and viewing explainable results.
        </p>
      </div>

      <ExecutePanel />
    </main>
  );
}

function ExecutePanel() {
  async function execute(formData: FormData) {
    "use server";
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

    const res = await fetch("/api/execute", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ intent, context }),
      cache: "no-store",
    });
    const body = await res.json();

    return body as { execution_id: string; status: string };
  }

  return (
    <section className="mt-6 grid gap-6 md:grid-cols-2">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-lg font-semibold">Create execution</h2>
        <form action={execute} className="mt-4 grid gap-3">
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
            className="mt-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold hover:bg-indigo-500"
          >
            Execute
          </button>
        </form>
        <p className="mt-3 text-xs text-zinc-400">
          After creating an execution, poll <code className="text-zinc-200">/api/executions/&lt;id&gt;</code>.
        </p>
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

