/**
 * The feed: the cards of every hackathon that is still current, plus taxonomy,
 * exchange rates and platform health, as one JSON document the web app filters
 * locally.
 *
 * It only changes when the home server commits a sync (every few hours), so it
 * is built once per version and kept at three levels:
 *  1. in this isolate's memory, re-checking the version at most once a minute
 *     (in the background, so requests never wait for that check);
 *  2. in this data centre's cache, keyed by version, for fresh isolates;
 *  3. in browsers, with the version as ETag (a returning visitor gets a 304).
 */

import type { Env, Item, SourceInfo } from "./env";
import { nowText } from "./http";

export interface Feed {
  version: string;
  generatedAt: string | null;
  etag: string;
  body: string;
  count: number;
  checkedAt: number;
  parsed?: { items: Item[]; sources: SourceInfo[] };
}

const RECHECK_MS = 60_000;

let current: Feed | undefined;
let inflight: Promise<Feed | null> | undefined;

/** The current feed, or null before the first sync has run. */
export async function getFeed(env: Env, ctx: ExecutionContext, origin: string): Promise<Feed | null> {
  if (current && Date.now() - current.checkedAt < RECHECK_MS) return current;
  if (current) {
    ctx.waitUntil(load(env, ctx, origin).catch((err) => console.error("feed refresh failed", err)));
    return current;
  }
  return load(env, ctx, origin);
}

/** After a commit: rebuild on the next request in this isolate. */
export function forgetFeed(): void {
  current = undefined;
}

export function parsedFeed(feed: Feed): { items: Item[]; sources: SourceInfo[] } {
  if (!feed.parsed) {
    const doc = JSON.parse(feed.body) as { items: Item[]; sources: SourceInfo[] };
    feed.parsed = { items: doc.items, sources: doc.sources };
  }
  return feed.parsed;
}

function load(env: Env, ctx: ExecutionContext, origin: string): Promise<Feed | null> {
  inflight ??= build(env, ctx, origin).finally(() => {
    inflight = undefined;
  });
  return inflight;
}

const cacheKey = (origin: string, version: string) => new Request(`${origin}/__feed/${encodeURIComponent(version)}`);

async function build(env: Env, ctx: ExecutionContext, origin: string): Promise<Feed | null> {
  const row = await env.DB.prepare("SELECT value FROM meta WHERE key = 'version'").first<{ value: string }>();
  if (!row) return null; // nothing synced yet
  const version = JSON.parse(row.value) as string;
  if (current?.version === version) {
    current.checkedAt = Date.now();
    return current;
  }

  const cache = caches.default;
  const hit = await cache.match(cacheKey(origin, version));
  if (hit) {
    current = {
      version,
      generatedAt: hit.headers.get("x-generated-at") || null,
      etag: `"${version}"`,
      body: await hit.text(),
      count: Number(hit.headers.get("x-count") ?? 0),
      checkedAt: Date.now(),
    };
    return current;
  }

  const [meta, rows] = await env.DB.batch<Record<string, string>>([
    env.DB.prepare("SELECT key, value FROM meta"),
    env.DB.prepare("SELECT card FROM hackathons WHERE listed_until > ?1 ORDER BY starts_at IS NULL, starts_at, id").bind(nowText()),
  ]);
  const m: Record<string, string> = {};
  for (const r of meta.results) m[r.key] = r.value;
  const cards = rows.results.map((r) => r.card);
  const v = m.version ? (JSON.parse(m.version) as string) : version;
  const generatedAt = m.generated_at ? (JSON.parse(m.generated_at) as string | null) : null;
  // the stored values are JSON already: join them as text instead of parsing and re-encoding
  const body =
    `{"version":1,"data_version":${JSON.stringify(v)},"generated_at":${m.generated_at ?? "null"},` +
    `"count":${cards.length},"taxonomy":${m.taxonomy ?? "{}"},"fx":${m.fx ?? "{}"},"sources":${m.sources ?? "[]"},` +
    `"items":[${cards.join(",")}]}`;
  current = { version: v, generatedAt, etag: `"${v}"`, body, count: cards.length, checkedAt: Date.now() };
  ctx.waitUntil(
    cache.put(
      cacheKey(origin, v),
      new Response(body, {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "public, max-age=86400",
          "x-count": String(cards.length),
          "x-generated-at": generatedAt ?? "",
        },
      }),
    ),
  );
  return current;
}
