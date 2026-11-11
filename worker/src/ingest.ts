/**
 * The write side, used only by the home server's sync job (backend/hackmash/sync.py).
 * Every call needs `Authorization: Bearer <INGEST_KEY>`.
 *
 *   GET  /api/ingest/state   id and content hash of every row, so the job sends only changes
 *   POST /api/ingest/upsert  a JSON array of rows (one transaction)
 *   POST /api/ingest/delete  a JSON array of ids
 *   POST /api/ingest/commit  taxonomy, fx, sources and the new version; readers switch to it
 *   GET  /api/ingest/og      content hash of every link-preview poster held
 *   PUT  /api/ingest/og/<id>?hash=<hash>   one poster (image/jpeg body)
 *
 * Rows arrive as one JSON array and are passed to SQLite as a single bound value
 * (json_each does the rest), so the Worker never parses them: a few milliseconds of
 * CPU per request whatever the size.
 */

import type { Env } from "./env";
import { forgetFeed } from "./feed";
import { fail, json, NO_STORE, nowText } from "./http";

const MAX_BODY = 1_900_000; // D1 takes at most 2 MB in one bound value
const MAX_POSTER = 1_500_000;

const UPSERT = `
INSERT INTO hackathons (id, source, title, card, detail, hash, starts_at, ends_at,
                        registration_deadline, submission_deadline, listed_until, blurb, og_hash, updated_at)
SELECT json_extract(value, '$.id'), json_extract(value, '$.source'), json_extract(value, '$.title'),
       json_extract(value, '$.card'), json_extract(value, '$.detail'), json_extract(value, '$.hash'),
       json_extract(value, '$.starts_at'), json_extract(value, '$.ends_at'),
       json_extract(value, '$.registration_deadline'), json_extract(value, '$.submission_deadline'),
       json_extract(value, '$.listed_until'), json_extract(value, '$.blurb'), json_extract(value, '$.og'), ?2
FROM json_each(?1) WHERE true
ON CONFLICT (id) DO UPDATE SET
  source = excluded.source, title = excluded.title, card = excluded.card, detail = excluded.detail,
  hash = excluded.hash, starts_at = excluded.starts_at, ends_at = excluded.ends_at,
  registration_deadline = excluded.registration_deadline, submission_deadline = excluded.submission_deadline,
  listed_until = excluded.listed_until, blurb = excluded.blurb, og_hash = excluded.og_hash, updated_at = excluded.updated_at`;

const SET_POSTER = `
INSERT INTO og_images (id, hash, image, updated_at)
SELECT ?1, ?2, ?3, ?4 WHERE EXISTS (SELECT 1 FROM hackathons WHERE id = ?1)
ON CONFLICT (id) DO UPDATE SET hash = excluded.hash, image = excluded.image, updated_at = excluded.updated_at`;

const DROP_ALIASES_OF_ROWS = "DELETE FROM aliases WHERE id IN (SELECT json_extract(value, '$.id') FROM json_each(?1))";

const INSERT_ALIASES = `
INSERT OR REPLACE INTO aliases (alias, id)
SELECT a.value, json_extract(r.value, '$.id') FROM json_each(?1) AS r, json_each(r.value, '$.aliases') AS a`;

const SET_META = "INSERT INTO meta (key, value) VALUES (?1, ?2) ON CONFLICT (key) DO UPDATE SET value = excluded.value";

async function authorized(request: Request, env: Env): Promise<boolean> {
  const key = env.INGEST_KEY ?? "";
  const header = request.headers.get("Authorization") ?? "";
  const given = new TextEncoder().encode(header.startsWith("Bearer ") ? header.slice(7) : "");
  const expected = new TextEncoder().encode(key);
  if (key.length < 32) return false; // not configured: the endpoint stays shut
  if (given.byteLength !== expected.byteLength) return false;
  return crypto.subtle.timingSafeEqual(given, expected);
}

/** SQL errors are the sender's fault (bad rows); anything else is worth a retry. */
function dbFailure(err: unknown): Response {
  const message = err instanceof Error ? err.message : String(err);
  console.error("ingest failed", message);
  return message.includes("SQLITE_") ? fail(400, `the database refused this batch: ${message}`) : fail(503, "database unavailable, retry");
}

export async function ingest(request: Request, env: Env, path: string): Promise<Response> {
  if (!(await authorized(request, env))) return fail(401, "unauthorized");
  const db = env.DB;
  try {
    if (path === "/api/ingest/state" && request.method === "GET") {
      const [rows, version] = await db.batch<Record<string, string>>([
        db.prepare("SELECT id, hash FROM hackathons"),
        db.prepare("SELECT value FROM meta WHERE key = 'version'"),
      ]);
      const hashes: Record<string, string> = {};
      for (const r of rows.results) hashes[r.id] = r.hash;
      const v = version.results[0]?.value;
      return json({ version: v ? JSON.parse(v) : null, hashes }, 200, NO_STORE);
    }

    if (path === "/api/ingest/og" && request.method === "GET") {
      const { results } = await db.prepare("SELECT id, hash FROM og_images").all<{ id: string; hash: string }>();
      return json({ hashes: Object.fromEntries(results.map((r) => [r.id, r.hash])) }, 200, NO_STORE);
    }

    const poster = path.match(/^\/api\/ingest\/og\/([^/]+)$/);
    if (poster && request.method === "PUT") {
      const id = decodeURIComponent(poster[1]);
      const hash = new URL(request.url).searchParams.get("hash") ?? "";
      if (!/^[0-9a-f]{8,64}$/.test(hash)) return fail(400, "hash is required");
      const image = new Uint8Array(await request.arrayBuffer());
      if (image.byteLength > MAX_POSTER) return fail(413, `posters are at most ${MAX_POSTER} bytes`);
      if (image[0] !== 0xff || image[1] !== 0xd8 || image[2] !== 0xff) return fail(415, "posters are JPEG images");
      const res = await db.prepare(SET_POSTER).bind(id, hash, image, nowText()).run();
      if (!res.meta.changes) return fail(404, "no such hackathon");
      return json({ id, hash }, 200, NO_STORE);
    }

    if (request.method !== "POST") return fail(405, "method not allowed");

    const body = await request.text();
    if (body.length > MAX_BODY) return fail(413, `send at most ${MAX_BODY} bytes per request`);

    if (path === "/api/ingest/upsert") {
      if (!body.trimStart().startsWith("[")) return fail(400, "expected a JSON array of rows");
      const [, upserted] = await db.batch([
        db.prepare(DROP_ALIASES_OF_ROWS).bind(body),
        db.prepare(UPSERT).bind(body, nowText()),
        db.prepare(INSERT_ALIASES).bind(body),
      ]);
      return json({ upserted: upserted.meta.changes }, 200, NO_STORE);
    }

    if (path === "/api/ingest/delete") {
      if (!body.trimStart().startsWith("[")) return fail(400, "expected a JSON array of ids");
      const [, deleted] = await db.batch([
        db.prepare("DELETE FROM aliases WHERE id IN (SELECT value FROM json_each(?1))").bind(body),
        db.prepare("DELETE FROM hackathons WHERE id IN (SELECT value FROM json_each(?1))").bind(body),
        db.prepare("DELETE FROM og_images WHERE id IN (SELECT value FROM json_each(?1))").bind(body),
      ]);
      return json({ deleted: deleted.meta.changes }, 200, NO_STORE);
    }

    if (path === "/api/ingest/commit") {
      let doc: Record<string, unknown>;
      try {
        doc = JSON.parse(body) as Record<string, unknown>;
      } catch {
        return fail(400, "expected a JSON object");
      }
      if (typeof doc.version !== "string" || !doc.version) return fail(400, "version is required");
      const values: [string, unknown][] = [
        ["generated_at", doc.generated_at ?? null],
        ["taxonomy", doc.taxonomy ?? {}],
        ["fx", doc.fx ?? {}],
        ["sources", doc.sources ?? []],
        ["version", doc.version], // last: readers switch versions only once everything else is in
      ];
      await db.batch([
        ...values.map(([k, v]) => db.prepare(SET_META).bind(k, JSON.stringify(v))),
        db.prepare("DELETE FROM og_images WHERE id NOT IN (SELECT id FROM hackathons)"),
      ]);
      forgetFeed();
      const live = await db.prepare("SELECT count(*) AS n FROM hackathons WHERE listed_until > ?1").bind(nowText()).first<{ n: number }>();
      return json({ version: doc.version, current: live?.n ?? 0 }, 200, NO_STORE);
    }
  } catch (err) {
    return dbFailure(err);
  }
  return fail(404, "no such ingest call");
}
