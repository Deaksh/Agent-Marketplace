import { backendBaseUrl } from "@/lib/backend";

function forwardHeaders(req: Request) {
  const h: Record<string, string> = { "content-type": "application/json" };
  const auth = req.headers.get("authorization");
  const org = req.headers.get("x-org-id");
  if (auth) h["authorization"] = auth;
  if (org) h["x-org-id"] = org;
  return h;
}

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const upstream = await fetch(`${backendBaseUrl()}/cases/${id}/transition`, {
    method: "POST",
    headers: forwardHeaders(req),
    body: await req.text(),
    cache: "no-store",
  });
  const ct = upstream.headers.get("content-type") || "application/json";
  const text = await upstream.text();
  return new Response(text, { status: upstream.status, headers: { "content-type": ct } });
}

