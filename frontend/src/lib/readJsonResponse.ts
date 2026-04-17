export async function readJsonResponse<T>(res: Response): Promise<T> {
  const text = await res.text();
  const ct = res.headers.get("content-type") ?? "";
  if (!res.ok) {
    throw new Error(
      `Request failed (${res.status}) ${ct}: ${text.slice(0, 280)}`,
    );
  }
  if (!ct.includes("application/json")) {
    throw new Error(
      `Expected JSON, got ${ct || "unknown"}: ${text.slice(0, 280)}`,
    );
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`Invalid JSON body: ${text.slice(0, 280)}`);
  }
}
