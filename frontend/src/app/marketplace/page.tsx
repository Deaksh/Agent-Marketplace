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
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Agent Marketplace</h1>
          <a className="text-sm text-zinc-300 underline" href="/">
            Back to executions
          </a>
        </div>
        <p className="mt-2 text-zinc-300">
          Browse versioned agents with contracts, cost estimates, and reliability signals.
        </p>
      </div>

      <div className="mt-6 grid gap-3">
        {data.agents?.length ? (
          data.agents.map(({ package: p, latest_version: v }) => (
            <a
              key={p.id}
              href={`/marketplace/${p.id}`}
              className="block rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5 hover:bg-zinc-900/60"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate text-lg font-semibold text-zinc-50">{p.name}</div>
                  <div className="mt-1 truncate text-sm text-zinc-400">
                    {p.publisher} · <span className="font-mono">{p.slug}</span>
                  </div>
                  {p.description ? <div className="mt-2 text-sm text-zinc-300">{p.description}</div> : null}
                </div>
                <div className="shrink-0 text-right text-xs text-zinc-400">
                  {v ? (
                    <>
                      <div>
                        v<span className="text-zinc-200">{v.version}</span> · {v.runtime}
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
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 text-zinc-300">
            <p>No marketplace agents are published in the database yet.</p>
            <p className="mt-3 text-sm text-zinc-400">
              For a dev demo, open{" "}
              <a className="text-zinc-200 underline" href="/api/marketplace/seed" target="_blank" rel="noreferrer">
                /api/marketplace/seed
              </a>{" "}
              once (idempotent), then reload this page. To run compliance workflows, use{" "}
              <a className="text-zinc-200 underline" href="/">
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

