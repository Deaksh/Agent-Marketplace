/** Same key as marketplace enablement — one default org per browser. */
export const ORG_STORAGE_KEY = "oel_org_id";

export async function ensureDefaultOrgId(): Promise<string> {
  const existing = localStorage.getItem(ORG_STORAGE_KEY);
  if (existing) return existing;
  const res = await fetch("/api/orgs?name=default", { method: "POST" });
  const body = (await res.json()) as { org_id?: string };
  if (!body.org_id) throw new Error("Failed to create org");
  localStorage.setItem(ORG_STORAGE_KEY, body.org_id);
  return body.org_id;
}
