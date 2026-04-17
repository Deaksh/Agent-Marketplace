export const dynamic = "force-dynamic";

import { MarketplaceEnable } from "@/components/MarketplaceEnable";
import { backendBaseUrl } from "@/lib/backend";
import { readJsonResponse } from "@/lib/readJsonResponse";

type AgentDetailResp = {
  package: {
    id: string;
    publisher: string;
    slug: string;
    name: string;
    description: string;
    categories: string[];
    tags: string[];
    created_at: string;
  };
  versions: {
    id: string;
    package_id: string;
    version: string;
    release_notes: string;
    runtime: string;
    builtin_agent_name?: string | null;
    endpoint_url?: string | null;
    prompt_template?: string | null;
    input_schema: unknown;
    output_schema: unknown;
    cost_estimate_usd: number;
    reliability_score: number;
    status: string;
    run_count: number;
    success_count: number;
    avg_latency_ms: number;
    created_at: string;
  }[];
};

async function fetchDetail(id: string): Promise<AgentDetailResp> {
  const res = await fetch(`${backendBaseUrl()}/marketplace/agents/${id}`, {
    cache: "no-store",
  });
  return readJsonResponse<AgentDetailResp>(res);
}

export default async function MarketplaceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const data = await fetchDetail(id);
  const p = data.package;

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold">{p.name}</h1>
            <div className="mt-1 text-sm text-zinc-400">
              {p.publisher} · <span className="font-mono">{p.slug}</span>
            </div>
            {p.description ? <p className="mt-3 text-zinc-300">{p.description}</p> : null}
          </div>
          <div className="flex items-center gap-2">
            <MarketplaceEnable packageId={p.id} />
            <a className="text-sm text-zinc-300 underline" href="/marketplace">
              Back
            </a>
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-3">
        <h2 className="text-lg font-semibold">Versions</h2>
        {data.versions.length ? (
          data.versions.map((v) => (
            <div key={v.id} className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm text-zinc-400">Version</div>
                  <div className="text-lg font-semibold text-zinc-50">v{v.version}</div>
                  <div className="mt-1 text-sm text-zinc-400">
                    {v.runtime}
                    {v.builtin_agent_name ? ` · builtin: ${v.builtin_agent_name}` : ""}
                  </div>
                </div>
                <div className="text-right text-xs text-zinc-400">
                  <div>
                    rel <span className="text-zinc-200">{v.reliability_score.toFixed(2)}</span>
                  </div>
                  <div>
                    est <span className="text-zinc-200">${v.cost_estimate_usd.toFixed(2)}</span>
                  </div>
                  <div>
                    runs <span className="text-zinc-200">{v.run_count}</span>
                  </div>
                </div>
              </div>

              {v.release_notes ? (
                <div className="mt-3 text-sm text-zinc-300">
                  <div className="text-xs text-zinc-400">Release notes</div>
                  <div className="mt-1 whitespace-pre-wrap">{v.release_notes}</div>
                </div>
              ) : null}

              <details className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-zinc-100">Schemas</summary>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div>
                    <div className="text-xs text-zinc-400">Input schema</div>
                    <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                      {JSON.stringify(v.input_schema, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-400">Output schema</div>
                    <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug">
                      {JSON.stringify(v.output_schema, null, 2)}
                    </pre>
                  </div>
                </div>
              </details>
            </div>
          ))
        ) : (
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 text-zinc-300">
            No versions yet.
          </div>
        )}
      </div>
    </main>
  );
}

