import { backendBaseUrl } from "@/lib/backend";

export async function GET(req: Request) {
  const auth = req.headers.get("authorization");
  const org = req.headers.get("x-org-id");
  const headers: Record<string, string> = {};
  if (auth) headers["authorization"] = auth;
  if (org) headers["x-org-id"] = org;

  const upstream = await fetch(`${backendBaseUrl()}/me`, {
    headers,
    cache: "no-store",
  });

  const ct = upstream.headers.get("content-type") || "";
  const text = await upstream.text();
  if (ct.includes("application/json")) {
    return new Response(text, { status: upstream.status, headers: { "content-type": "application/json" } });
  }
  return new Response(text, { status: upstream.status, headers: { "content-type": ct || "text/plain" } });
}

