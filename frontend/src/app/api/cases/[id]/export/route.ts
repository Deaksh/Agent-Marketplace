import { backendBaseUrl } from "@/lib/backend";

function forwardHeaders(req: Request) {
  const h: Record<string, string> = {};
  const auth = req.headers.get("authorization");
  const org = req.headers.get("x-org-id");
  if (auth) h["authorization"] = auth;
  if (org) h["x-org-id"] = org;
  return h;
}

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const url = new URL(req.url);
  const format = (url.searchParams.get("format") || "json").toLowerCase();

  const upstream = await fetch(`${backendBaseUrl()}/cases/${id}/export?format=${encodeURIComponent(format)}`, {
    headers: forwardHeaders(req),
    cache: "no-store",
  });

  // Pass-through body + content-type so PDFs render in a tab.
  const contentType = upstream.headers.get("content-type") || "application/octet-stream";
  const buf = await upstream.arrayBuffer();
  return new Response(buf, { status: upstream.status, headers: { "content-type": contentType } });
}

