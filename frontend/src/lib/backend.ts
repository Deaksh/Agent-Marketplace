/**
 * Base URL for FastAPI from the Next.js server (Server Components, Route Handlers).
 * Browser requests should keep using `/api/...` so next.config rewrites apply.
 *
 * Override when the API is not on localhost:8040 from the Next process
 * (e.g. Docker service name).
 */
export function backendBaseUrl(): string {
  return (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8040").replace(/\/$/, "");
}
