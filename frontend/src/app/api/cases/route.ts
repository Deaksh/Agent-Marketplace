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

export async function GET(req: Request) {
  const url = new URL(req.url);
  const upstream = await fetch(`${backendBaseUrl()}/cases?${url.searchParams.toString()}`, {
    headers: forwardHeaders(req),
    cache: "no-store",
  });
  const body = await readJsonResponse(upstream);
  return Response.json(body, { status: upstream.status });
}

export async function POST(req: Request) {
  const upstream = await fetch(`${backendBaseUrl()}/cases`, {
    method: "POST",
    headers: forwardHeaders(req),
    body: await req.text(),
    cache: "no-store",
  });
  const body = await readJsonResponse(upstream);
  return Response.json(body, { status: upstream.status });
}

