import { backendBaseUrl } from "@/lib/backend";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const r = await fetch(`${backendBaseUrl()}/marketplace/agents`, {
    cache: "no-store",
  });
  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: {
      "content-type": r.headers.get("content-type") ?? "application/json",
    },
  });
}
