export const dynamic = "force-dynamic";

import { backendBaseUrl } from "@/lib/backend";
import { readJsonResponse } from "@/lib/readJsonResponse";

type RegulationUnit = {
  id: number;
  regulation_code: string;
  unit_id: string;
  title: string;
  version: string;
  text: string;
};

type UnitsResp = { limit: number; offset: number; units: RegulationUnit[] };

async function fetchUnits(searchParams: Record<string, string | string[] | undefined>): Promise<UnitsResp> {
  const q = typeof searchParams.q === "string" ? searchParams.q : "";
  const regulationCode = typeof searchParams.regulation_code === "string" ? searchParams.regulation_code : "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (regulationCode) params.set("regulation_code", regulationCode);
  params.set("limit", "50");
  params.set("offset", "0");

  const res = await fetch(`${backendBaseUrl()}/regulations/units?${params.toString()}`, { cache: "no-store" });
  return readJsonResponse<UnitsResp>(res);
}

export default async function RegulationsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q : "";
  const regulationCode = typeof sp.regulation_code === "string" ? sp.regulation_code : "";
  const data = await fetchUnits(sp);

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">Regulations</h1>
          <div className="flex items-center gap-3 text-sm">
            <a className="text-zinc-300 underline" href="/">
              Executions
            </a>
            <a className="text-zinc-300 underline" href="/marketplace">
              Marketplace
            </a>
          </div>
        </div>
        <p className="mt-2 text-zinc-300">
          Browse and search regulation units (from `regulation_units`). This is your content catalog layer.
        </p>
      </div>

      <div className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
        <form className="grid gap-3 md:grid-cols-3" action="/regulations" method="get">
          <label className="grid gap-1">
            <span className="text-xs text-zinc-400">Regulation code</span>
            <input
              name="regulation_code"
              defaultValue={regulationCode}
              placeholder="GDPR"
              className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600"
            />
          </label>
          <label className="grid gap-1 md:col-span-2">
            <span className="text-xs text-zinc-400">Search</span>
            <input
              name="q"
              defaultValue={q}
              placeholder="e.g. retention, Art. 5, processor, DPIA"
              className="rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600"
            />
          </label>
          <div className="flex items-end justify-between gap-3 md:col-span-3">
            <div className="text-xs text-zinc-500">
              Showing <span className="text-zinc-200">{data.units.length}</span> units
            </div>
            <button
              type="submit"
              className="rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-800"
            >
              Search
            </button>
          </div>
        </form>
      </div>

      <div className="mt-6 grid gap-3">
        {data.units.length ? (
          data.units.map((u) => (
            <div key={u.id} className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-zinc-100">
                    {u.regulation_code} · {u.unit_id} {u.title ? `— ${u.title}` : ""}
                  </div>
                  <div className="mt-1 text-[11px] text-zinc-500">v{u.version}</div>
                </div>
              </div>
              <div className="mt-3 whitespace-pre-wrap text-[12px] leading-snug text-zinc-300">{u.text}</div>
            </div>
          ))
        ) : (
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 text-zinc-300">
            No units found. If this is a fresh Codespace, seed GDPR units at{" "}
            <a className="text-zinc-200 underline" href="/api/regulations/seed" target="_blank" rel="noreferrer">
              /api/regulations/seed
            </a>{" "}
            and retry.
          </div>
        )}
      </div>
    </main>
  );
}

