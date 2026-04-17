"use client";

import { useEffect, useState } from "react";

const ORG_STORAGE_KEY = "oel_org_id";

async function ensureDefaultOrg(): Promise<string> {
  const existing = localStorage.getItem(ORG_STORAGE_KEY);
  if (existing) return existing;
  const res = await fetch("/api/orgs?name=default", { method: "POST" });
  const body = (await res.json()) as { org_id?: string };
  if (!body.org_id) throw new Error("Failed to create org");
  localStorage.setItem(ORG_STORAGE_KEY, body.org_id);
  return body.org_id;
}

export function MarketplaceEnable({ packageId }: { packageId: string }) {
  const [orgId, setOrgId] = useState<string>("");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const id = await ensureDefaultOrg();
        setOrgId(id);
        const res = await fetch(`/api/orgs/${id}/agents`, { cache: "no-store" });
        const body = (await res.json()) as { enabled?: { package_id: string; enabled: boolean }[] };
        const row = (body.enabled || []).find((e) => e.package_id === packageId);
        setEnabled(row ? !!row.enabled : false);
      } catch {
        setEnabled(false);
      }
    })();
  }, [packageId]);

  async function toggle() {
    if (!orgId || enabled === null) return;
    setBusy(true);
    try {
      if (!enabled) {
        await fetch(`/api/orgs/${orgId}/agents/${packageId}/enable`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ enabled: true, pinned_version_id: null, policy: {} }),
        });
        setEnabled(true);
      } else {
        await fetch(`/api/orgs/${orgId}/agents/${packageId}/disable`, { method: "POST" });
        setEnabled(false);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      disabled={busy || enabled === null}
      onClick={toggle}
      className={
        "rounded-lg border px-3 py-1.5 text-xs font-semibold " +
        (enabled
          ? "border-emerald-700 bg-emerald-950/40 text-emerald-100 hover:bg-emerald-950/60"
          : "border-zinc-700 bg-zinc-900 text-zinc-100 hover:bg-zinc-800") +
        " disabled:opacity-60"
      }
    >
      {enabled === null ? "…" : enabled ? "Enabled" : "Enable"}
    </button>
  );
}

