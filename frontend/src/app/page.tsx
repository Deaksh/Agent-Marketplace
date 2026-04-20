import { ExecutePanel } from "@/components/ExecutePanel";

export default function Page() {
  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-r from-indigo-500/10 via-cyan-500/10 to-fuchsia-500/10 p-6 ring-1 ring-white/5">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Outcome Execution Layer</h1>
          <div className="flex items-center gap-3 text-sm">
            <a className="text-slate-200 underline decoration-emerald-400/50 hover:text-white" href="/cases">
              Cases
            </a>
            <a className="text-slate-200 underline decoration-indigo-400/50 hover:text-white" href="/regulations">
              Regulations
            </a>
            <a className="text-slate-200 underline decoration-cyan-400/50 hover:text-white" href="/marketplace">
              Marketplace
            </a>
          </div>
        </div>
        <p className="mt-2 text-slate-200/90">
          API-first MVP for regulatory compliance workflows. This UI is a thin client
          for creating executions and viewing explainable results.
        </p>
      </div>

      <ExecutePanel />
    </main>
  );
}
