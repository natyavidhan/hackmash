export const CORS = { "Access-Control-Allow-Origin": "*" } as const;
export const NO_STORE = { "Cache-Control": "no-store" } as const;

export function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS, ...headers },
  });
}

export function fail(status: number, message: string): Response {
  return json({ error: message }, status, NO_STORE);
}

/** Does If-None-Match name this ETag? (Cloudflare weakens ETags when it compresses.) */
export function etagMatches(request: Request, etag: string): boolean {
  const header = request.headers.get("If-None-Match");
  if (!header) return false;
  const bare = etag.replace(/^W\//, "");
  return header.split(",").some((tag) => {
    const t = tag.trim();
    return t === "*" || t.replace(/^W\//, "") === bare;
  });
}

/** Serve from this data centre's cache, or make the response and keep it for `ttl` seconds. */
export async function edgeCached(
  request: Request,
  ctx: ExecutionContext,
  ttl: number,
  make: () => Promise<Response>,
): Promise<Response> {
  const cache = caches.default;
  const key = new Request(request.url, { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return hit;
  const res = await make();
  if (res.status === 200) {
    res.headers.set("Cache-Control", `public, max-age=${ttl}`);
    ctx.waitUntil(cache.put(key, res.clone()));
  }
  return res;
}

/** UTC now in the database's text format: 2026-11-11T12:00:00Z. */
export function nowText(): string {
  return `${new Date().toISOString().slice(0, 19)}Z`;
}
