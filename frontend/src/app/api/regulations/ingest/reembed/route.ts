import { backendBaseUrl } from "@/lib/backend";
import { readJsonResponse } from "@/lib/readJsonResponse";

export async function POST(req: Request) {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const upstream = await fetch(`${backendBaseUrl()}/regulations/ingest/reembed${qs ? `?${qs}` : ""}`, {
    method: "POST",
    cache: "no-store",
  });
  const body = await readJsonResponse(upstream);
  return Response.json(body, { status: upstream.status });
}
