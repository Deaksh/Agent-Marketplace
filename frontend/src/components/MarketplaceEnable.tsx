"use client";

import { ensureDemoSession } from "@/lib/authSession";
import { useEffect, useState } from "react";

export function MarketplaceEnable({ packageId }: { packageId: string }) {
  const [orgId, setOrgId] = useState<string>("");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const sess = await ensureDemoSession();
        setOrgId(sess.orgId);
        const res = await fetch(`/api/orgs/${sess.orgId}/agents`, {
          cache: "no-store",
          headers: { Authorization: `Bearer ${sess.accessToken}`, "X-Org-Id": sess.orgId },
        });
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
      const sess = await ensureDemoSession();
      if (!enabled) {
        await fetch(`/api/orgs/${orgId}/agents/${packageId}/enable`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            Authorization: `Bearer ${sess.accessToken}`,
            "X-Org-Id": sess.orgId,
          },
          body: JSON.stringify({ enabled: true, pinned_version_id: null, policy: {} }),
        });
        setEnabled(true);
      } else {
        await fetch(`/api/orgs/${orgId}/agents/${packageId}/disable`, {
          method: "POST",
          headers: { Authorization: `Bearer ${sess.accessToken}`, "X-Org-Id": sess.orgId },
        });
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
          ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/15"
          : "border-slate-700/80 bg-slate-900/60 text-slate-100 hover:bg-slate-900/80") +
        " disabled:opacity-60"
      }
    >
      {enabled === null ? "…" : enabled ? "Enabled" : "Enable"}
    </button>
  );
}

