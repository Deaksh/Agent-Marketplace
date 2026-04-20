export const TOKEN_STORAGE_KEY = "oel_access_token";
export const ORG_STORAGE_KEY = "oel_org_id";

type AuthResp = { access_token?: string; org_id?: string };

export function getAccessToken(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function getOrgId(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(ORG_STORAGE_KEY);
}

export async function ensureDemoSession(): Promise<{ accessToken: string; orgId: string }> {
  const t = getAccessToken();
  const o = getOrgId();
  if (t && o) return { accessToken: t, orgId: o };

  const email = "demo@oel.local";
  const password = "demo-demo-123";

  // Try register first (idempotent-ish); if already exists, login.
  let body: AuthResp | null = null;
  try {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password, org_name: "default" }),
    });
    if (res.ok) body = (await res.json()) as AuthResp;
  } catch {
    body = null;
  }

  if (!body?.access_token) {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    body = (await res.json()) as AuthResp;
  }

  if (!body?.access_token || !body?.org_id) throw new Error("Failed to establish demo session");
  localStorage.setItem(TOKEN_STORAGE_KEY, body.access_token);
  localStorage.setItem(ORG_STORAGE_KEY, body.org_id);
  return { accessToken: body.access_token, orgId: body.org_id };
}

