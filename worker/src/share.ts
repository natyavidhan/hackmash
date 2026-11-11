/**
 * Link previews. WhatsApp, X, LinkedIn, Slack and Discord read a page's <meta>
 * tags without running JavaScript, so for a shared notice (/?h=<id>) the Worker
 * rewrites the app's index.html with that hackathon's title, the line written by
 * the sync (`blurb`) and its poster:
 *
 *   GET /?h=<id>        index.html with the hackathon's og:/twitter: tags
 *   GET /og/<id>.jpg    the poster (1200×630 JPEG drawn by the home server);
 *                       ?v=<hash> URLs are immutable, so apps re-fetch when it changes
 */

import type { Env } from "./env";
import { CORS } from "./http";

const DEFAULT_POSTER = "/og-default.jpg"; // the site's own card, 1280×640

/** Where links should point: https://hackmash.xyz for our own hosts, else (local dev) where we were asked. */
const siteOrigin = (url: URL) => (/(^|\.)hackmash\.xyz$/.test(url.hostname) ? "https://hackmash.xyz" : url.origin);

const RESOLVE_ID = "COALESCE((SELECT a.id FROM aliases AS a WHERE a.alias = ?1), ?1)";

export async function poster(request: Request, env: Env, ctx: ExecutionContext, id: string, url: URL): Promise<Response> {
  const cache = caches.default;
  const key = new Request(url.toString(), { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return hit;

  const row = await env.DB.prepare(`SELECT hash, image FROM og_images WHERE id = ${RESOLVE_ID}`)
    .bind(id)
    .first<{ hash: string; image: ArrayBuffer | number[] }>();
  if (!row) {
    // not drawn yet (or never will be): the site's card, kept briefly so the real one shows up soon
    const fallback = await env.ASSETS.fetch(new Request(new URL(DEFAULT_POSTER, url)));
    const res = new Response(fallback.body, fallback);
    res.headers.set("Cache-Control", "public, max-age=600");
    return res;
  }
  const bytes = row.image instanceof ArrayBuffer ? row.image : new Uint8Array(row.image).buffer;
  const fresh = url.searchParams.get("v") === row.hash;
  const res = new Response(bytes, {
    headers: {
      "Content-Type": "image/jpeg",
      ETag: `"${row.hash}"`,
      "Cache-Control": fresh ? "public, max-age=31536000, immutable" : "public, max-age=3600",
      ...CORS,
    },
  });
  ctx.waitUntil(cache.put(key, res.clone()));
  return res;
}

/** The app's index.html; for /?h=<id>, with that hackathon's preview tags. */
export async function page(request: Request, env: Env, url: URL): Promise<Response> {
  const id = url.searchParams.get("h");
  if (!id) return env.ASSETS.fetch(request);

  const [html, row] = await Promise.all([
    // a plain GET for "/": no conditional headers, so it always has a body to rewrite
    env.ASSETS.fetch(new Request(new URL("/", url), { headers: { Accept: "text/html" } })),
    env.DB.prepare(
      `SELECT h.id AS id, h.title AS title, h.blurb AS blurb, o.hash AS og
       FROM hackathons AS h LEFT JOIN og_images AS o ON o.id = h.id WHERE h.id = ${RESOLVE_ID}`,
    )
      .bind(id)
      .first<{ id: string; title: string; blurb: string | null; og: string | null }>(),
  ]);
  if (!row || !html.ok || !(html.headers.get("Content-Type") ?? "").includes("text/html")) return html;

  const origin = siteOrigin(url);
  const link = `${origin}/?h=${encodeURIComponent(row.id)}`;
  const image = row.og ? `${origin}/og/${encodeURIComponent(row.id)}.jpg?v=${row.og}` : `${origin}${DEFAULT_POSTER}`;
  const description = row.blurb || "Every hackathon from every platform, on one board.";
  const content = (value: string) => ({
    element(el: Element) {
      el.setAttribute("content", value);
    },
  });
  const res = new HTMLRewriter()
    .on("title", {
      element(el) {
        el.setInnerContent(`${row.title} · Hackmash`);
      },
    })
    .on("head", {
      element(el) {
        el.append(`<link rel="canonical" href="${link}">`, { html: true }); // link is URL-encoded: no quotes
      },
    })
    .on('meta[name="description"]', content(description))
    .on('meta[property="og:type"]', content("article"))
    .on('meta[property="og:title"]', content(row.title))
    .on('meta[property="og:description"]', content(description))
    .on('meta[property="og:url"]', content(link))
    .on('meta[property="og:image"]', content(image))
    .on('meta[property="og:image:width"]', content(row.og ? "1200" : "1280"))
    .on('meta[property="og:image:height"]', content(row.og ? "630" : "640"))
    .on('meta[property="og:image:alt"]', content(`${row.title}: ${description}`))
    .on('meta[name="twitter:title"]', content(row.title))
    .on('meta[name="twitter:description"]', content(description))
    .on('meta[name="twitter:image"]', content(image))
    .transform(html);
  const out = new Response(res.body, res);
  out.headers.delete("ETag"); // the body is no longer the asset's
  out.headers.set("Cache-Control", "no-cache");
  return out;
}
