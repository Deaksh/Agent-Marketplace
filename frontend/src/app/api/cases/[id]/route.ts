import { backendBaseUrl } from "@/lib/backend";
import { readJsonResponse } from "@/lib/readJsonResponse";

function forwardHeaders(req: Request) {
  const h: Record<string, string> = { "content-type": "application/json" };
  const auth = req.headers.get("authorization");
  const org = req.headers.get("x-org-id");
  if (auth) h["authorization"] = auth;
  if (org) h["x-org-id"] = org;
  return h;
}

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const upstream = await fetch(`${backendBaseUrl()}/cases/${id}`, {
    headers: forwardHeaders(req),
    cache: "no-store",
  });
  const body = await readJsonResponse(upstream);
  return Response.json(body, { status: upstream.status });
}

