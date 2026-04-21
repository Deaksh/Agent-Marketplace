import { backendBaseUrl } from "@/lib/backend";

export async function POST(req: Request) {
  const upstream = await fetch(`${backendBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  const ct = upstream.headers.get("content-type") || "application/json";
  const text = await upstream.text();
  return new Response(text, { status: upstream.status, headers: { "content-type": ct } });
}

