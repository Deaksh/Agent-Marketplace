import { ExecutePanel } from "@/components/ExecutePanel";

export default function Page() {
  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Outcome Execution Layer</h1>
          <div className="flex items-center gap-3 text-sm">
            <a className="text-zinc-300 underline" href="/regulations">
              Regulations
            </a>
            <a className="text-zinc-300 underline" href="/marketplace">
              Marketplace
            </a>
          </div>
        </div>
        <p className="mt-2 text-zinc-300">
          API-first MVP for regulatory compliance workflows. This UI is a thin client
          for creating executions and viewing explainable results.
        </p>
      </div>

      <ExecutePanel />
    </main>
  );
}
