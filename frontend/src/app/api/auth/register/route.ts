import { backendBaseUrl } from "@/lib/backend";
import { readJsonResponse } from "@/lib/readJsonResponse";

export async function POST(req: Request) {
  const upstream = await fetch(`${backendBaseUrl()}/auth/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  const body = await readJsonResponse(upstream);
  return Response.json(body, { status: upstream.status });
}

