/**
 * Hackmash on Cloudflare Workers.
 *
 * Static assets (the React app) are served straight from Cloudflare's edge; only
 * /api/* and /data/* run this Worker, which reads Cloudflare D1. The data is
 * written by the home server's sync job through /api/ingest/* (see ingest.ts).
 *
 *   GET /api/catalog                        the feed the web app filters locally (ETag + 304)
 *   GET /api/hackathons                     search for scripts and integrations (see search.ts)
 *   GET /api/hackathons/{id}                one listing, ended ones too (also resolves merged ids)
 *   GET /api/hackathons/{id}/calendar.ics   the event and its deadlines, with reminders
 *   GET /api/calendar.ics?ids=a,b           a subscribable calendar for someone's tabs
 *   GET /api/sources                        platforms and how their last fetch went
 *   GET /api/health                         liveness and data freshness
 */

import type { Env, Item } from "./env";
import { getFeed, parsedFeed, type Feed } from "./feed";
import { CORS, edgeCached, etagMatches, fail, json, NO_STORE } from "./http";
import { calendar } from "./ics";
import { ingest } from "./ingest";
import { enrich } from "./lifecycle";
import { search } from "./search";

const API_VERSION = "0.2.0";
const STALE_AFTER = 12 * 3_600_000;
const MAX_IDS = 300;

const splitIds = (values: string[]) =>
  values
    .flatMap((v) => v.split(","))
    .map((v) => v.trim())
    .filter(Boolean);

/** Rows by id, resolving the ids of duplicates merged into another listing; in the order asked. */
async function itemsByIds(env: Env, ids: string[]): Promise<Item[]> {
  if (!ids.length) return [];
  const { results } = await env.DB.prepare(
    `SELECT h.detail AS detail FROM json_each(?1) AS j
     JOIN hackathons AS h ON h.id = COALESCE((SELECT a.id FROM aliases AS a WHERE a.alias = j.value), j.value)
     ORDER BY j.key`,
  )
    .bind(JSON.stringify(ids.slice(0, MAX_IDS)))
    .all<{ detail: string }>();
  const seen = new Set<string>();
  const out: Item[] = [];
  for (const r of results) {
    const item = JSON.parse(r.detail) as Item;
    if (!seen.has(item.id)) {
      seen.add(item.id);
      out.push(item);
    }
  }
  return out;
}

function sourceNames(feed: Feed | null): Record<string, string> {
  if (!feed) return {};
  return Object.fromEntries(parsedFeed(feed).sources.map((s) => [s.key, s.name]));
}

function ics(body: string, filename: string): Response {
  return new Response(body, {
    headers: {
      "Content-Type": "text/calendar; charset=utf-8",
      "Content-Disposition": `inline; filename="${filename}"`,
      ...CORS,
    },
  });
}

const notYet = () => fail(503, "The board is being put up for the first time. Give it a minute and retry.");

async function route(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;

  if (path.startsWith("/api/ingest/")) return ingest(request, env, path);
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: { ...CORS, "Access-Control-Allow-Methods": "GET, HEAD", "Access-Control-Max-Age": "86400" } });
  }
  if (request.method !== "GET" && request.method !== "HEAD") return fail(405, "method not allowed");

  if (path === "/api/catalog" || path === "/data/catalog.json") {
    const feed = await getFeed(env, ctx, url.origin);
    if (!feed) return notYet();
    const headers = {
      "Content-Type": "application/json; charset=utf-8",
      ETag: feed.etag,
      "Cache-Control": "public, max-age=60, stale-while-revalidate=600",
      ...CORS,
    };
    if (etagMatches(request, feed.etag)) return new Response(null, { status: 304, headers });
    return new Response(feed.body, { headers });
  }

  if (path === "/api/health") {
    const feed = await getFeed(env, ctx, url.origin);
    const generated = feed?.generatedAt ? Date.parse(feed.generatedAt) : undefined;
    return json(
      {
        ok: !!feed,
        version: API_VERSION,
        data_version: feed?.version ?? null,
        generated_at: feed?.generatedAt ?? null,
        count: feed?.count ?? 0,
        stale: generated === undefined || Date.now() - generated > STALE_AFTER,
      },
      200,
      NO_STORE,
    );
  }

  if (path === "/api/sources") {
    const feed = await getFeed(env, ctx, url.origin);
    if (!feed) return notYet();
    return json({ generated_at: feed.generatedAt, sources: parsedFeed(feed).sources }, 200, { "Cache-Control": "public, max-age=300" });
  }

  if (path === "/api/hackathons") {
    const feed = await getFeed(env, ctx, url.origin);
    if (!feed) return notYet();
    const names = sourceNames(feed);
    const now = Date.now();
    const ids = splitIds(url.searchParams.getAll("ids"));
    if (ids.length) {
      const items = (await itemsByIds(env, ids)).map((it) => enrich(it, now, names));
      return json({ total: items.length, page: 1, page_size: items.length, generated_at: feed.generatedAt, items }, 200, {
        "Cache-Control": "public, max-age=300",
      });
    }
    const result = search(parsedFeed(feed).items, url.searchParams, names, now);
    return json({ ...result, generated_at: feed.generatedAt }, 200, { "Cache-Control": "public, max-age=60" });
  }

  if (path === "/api/calendar.ics") {
    return edgeCached(request, ctx, 1800, async () => {
      const ids = splitIds(url.searchParams.getAll("ids"));
      const name = `Hackmash: ${url.searchParams.get("name") || "My hackathons"}`.slice(0, 80);
      const names = sourceNames(await getFeed(env, ctx, url.origin));
      return ics(calendar(await itemsByIds(env, ids), name, names), "hackmash.ics");
    });
  }

  const one = path.match(/^\/api\/hackathons\/([^/]+?)(\/calendar\.ics)?$/);
  if (one) {
    let id: string;
    try {
      id = decodeURIComponent(one[1]);
    } catch {
      return fail(400, "bad id");
    }
    return edgeCached(request, ctx, one[2] ? 1800 : 300, async () => {
      const [item] = await itemsByIds(env, [id]);
      if (!item) return fail(404, "No such hackathon. It may have ended more than 90 days ago or been taken down.");
      const names = sourceNames(await getFeed(env, ctx, url.origin));
      if (one[2]) return ics(calendar([item], item.title, names), `${item.id}.ics`);
      return json(enrich(item, Date.now(), names));
    });
  }

  return fail(404, "no such endpoint");
}

export default {
  async fetch(request, env, ctx): Promise<Response> {
    try {
      const res = await route(request, env, ctx);
      return request.method === "HEAD" ? new Response(null, res) : res;
    } catch (err) {
      console.error("request failed", err);
      return fail(500, "Something went wrong on our side.");
    }
  },
} satisfies ExportedHandler<Env>;
