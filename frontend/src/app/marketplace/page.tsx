export const dynamic = "force-dynamic";

import { backendBaseUrl } from "@/lib/backend";
import { readJsonResponse } from "@/lib/readJsonResponse";

type Package = {
  id: string;
  publisher: string;
  slug: string;
  name: string;
  description: string;
  categories: string[];
  tags: string[];
  created_at: string;
};

type VersionSummary = {
  id: string;
  version: string;
  runtime: string;
  status: string;
  cost_estimate_usd: number;
  reliability_score: number;
  run_count: number;
  success_count: number;
  avg_latency_ms: number;
  created_at: string;
};

type MarketplaceListResp = {
  agents: { package: Package; latest_version: VersionSummary | null }[];
};

async function fetchAgents(): Promise<MarketplaceListResp> {
  const res = await fetch(`${backendBaseUrl()}/marketplace/agents`, {
    cache: "no-store",
  });
  return readJsonResponse<MarketplaceListResp>(res);
}

export default async function MarketplacePage() {
  const data = await fetchAgents();
  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-r from-cyan-500/10 via-indigo-500/10 to-fuchsia-500/10 p-6 ring-1 ring-white/5">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Agent Marketplace</h1>
          <div className="flex items-center gap-3 text-sm">
            <a className="text-slate-200 underline decoration-indigo-400/50 hover:text-white" href="/">
              Executions
            </a>
            <a className="text-slate-200 underline decoration-emerald-400/50 hover:text-white" href="/cases">
              Cases
            </a>
            <a className="text-slate-200 underline decoration-cyan-400/50 hover:text-white" href="/regulations">
              Regulations
            </a>
          </div>
        </div>
        <p className="mt-2 text-slate-200/90">
          Browse versioned agents with contracts, cost estimates, and reliability signals.
        </p>
      </div>

      <div className="mt-6 grid gap-3">
        {data.agents?.length ? (
          data.agents.map(({ package: p, latest_version: v }) => (
            <a
              key={p.id}
              href={`/marketplace/${p.id}`}
              className="block rounded-2xl border border-slate-800/80 bg-slate-900/35 p-5 ring-1 ring-white/5 hover:bg-slate-900/50"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate text-lg font-semibold text-slate-50">{p.name}</div>
                  <div className="mt-1 truncate text-sm text-slate-300/80">
                    {p.publisher} · <span className="font-mono">{p.slug}</span>
                  </div>
                  {p.description ? <div className="mt-2 text-sm text-slate-200/90">{p.description}</div> : null}
                </div>
                <div className="shrink-0 text-right text-xs text-slate-300/80">
                  {v ? (
                    <>
                      <div>
                        v<span className="text-slate-100">{v.version}</span> · {v.runtime}
                      </div>
                      <div className="mt-1">
                        rel {v.reliability_score.toFixed(2)} · ${v.cost_estimate_usd.toFixed(2)}
                      </div>
                    </>
                  ) : (
                    <div>No versions</div>
                  )}
                </div>
              </div>
            </a>
          ))
        ) : (
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/35 p-6 text-slate-200 ring-1 ring-white/5">
            <p>No marketplace agents are published in the database yet.</p>
            <p className="mt-3 text-sm text-slate-300/80">
              For a dev demo, open{" "}
              <a
                className="text-slate-100 underline decoration-indigo-400/50 hover:text-white"
                href="/api/marketplace/seed"
                target="_blank"
                rel="noreferrer"
              >
                /api/marketplace/seed
              </a>{" "}
              once (idempotent), then reload this page. To run compliance workflows, use{" "}
              <a className="text-slate-100 underline decoration-cyan-400/50 hover:text-white" href="/">
                Executions
              </a>
              .
            </p>
          </div>
        )}
      </div>
    </main>
  );
}

