/**
 * GET /api/hackathons: server-side search for scripts and integrations
 * (the web app filters the feed itself). Mirrors backend `hackmash/query.py`,
 * over what is current: ended events are only reachable by id.
 */

import type { Item } from "./env";
import { enrich, lifecycle, ms, nextDeadline } from "./lifecycle";

const list = (p: URLSearchParams, key: string) =>
  p
    .getAll(key)
    .flatMap((v) => v.split(","))
    .map((v) => v.trim())
    .filter(Boolean);

const flag = (p: URLSearchParams, key: string) => ["1", "true", "yes"].includes((p.get(key) ?? "").toLowerCase());

const escapeRx = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Short terms ("ai", "ml") match at the start of a word, so "ai" doesn't hit "Chennai". */
function termMatcher(term: string): (text: string) => boolean {
  if (term.length > 3) return (text) => text.includes(term);
  const rx = new RegExp(`(^|[^\\p{L}\\p{N}])${escapeRx(term)}`, "u");
  return (text) => rx.test(text);
}

export function search(items: Item[], p: URLSearchParams, names: Record<string, string>, now: number) {
  const terms = (p.get("q") ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  const matchers = terms.map(termMatcher);
  const sources = list(p, "source");
  const modes = list(p, "mode");
  const kinds = list(p, "kind");
  const themes = list(p, "theme");
  const audiences = list(p, "audience");
  const countries = list(p, "country");
  const states = list(p, "state");
  const cities = list(p, "city");
  const regions = list(p, "region");
  const statuses = new Set(list(p, "status").length ? list(p, "status") : ["open", "live", "upcoming"]);
  const minPrize = Number(p.get("min_prize_usd") ?? 0) || 0;
  const beginner = flag(p, "beginner");
  const free = flag(p, "free");

  const found: { score: number; item: Item }[] = [];
  for (const it of items) {
    if (sources.length && !sources.includes(it.source) && !(it.also_on ?? []).some((a) => sources.includes(a.source))) continue;
    if (modes.length && !modes.includes(it.mode ?? "")) continue;
    if (kinds.length && !kinds.includes(it.kind ?? "hackathon")) continue;
    if (themes.length && !(it.themes ?? []).some((t) => themes.includes(t))) continue;
    if (audiences.length && !(it.audience ?? []).some((a) => audiences.includes(a))) continue;
    if (countries.length && !countries.includes(it.country ?? "")) continue;
    if (states.length && !states.includes(it.state ?? "")) continue;
    if (cities.length && !cities.includes(it.city ?? "")) continue;
    if (regions.length && !regions.includes(it.region ?? "")) continue;
    if (minPrize && (it.prize_usd ?? 0) < minPrize) continue;
    if (beginner && !it.beginner_friendly) continue;
    if (free && it.registration_fee) continue;
    const { status, regOpen } = lifecycle(it, now);
    if (!statuses.has(status) && !(regOpen && statuses.has("open"))) continue;
    if (it.delisted && status !== "live") continue; // the platform took it down
    let score = 0;
    if (terms.length) {
      const text = [it.title, it.organizer, it.tagline, it.location, it.city, it.state, it.country, names[it.source], ...(it.tags ?? [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!matchers.every((m) => m(text))) continue;
      const title = it.title.toLowerCase();
      score = terms.reduce((s, t) => s + (title.includes(t) ? 3 : 1), 0);
    }
    found.push({ score, item: it });
  }

  const far = Number.MAX_SAFE_INTEGER;
  const sort = p.get("sort") ?? "deadline";
  const by = {
    relevance: (a: Item, b: Item, sa: number, sb: number) => sb - sa,
    starts: (a: Item, b: Item) => (ms(a.starts_at) ?? far) - (ms(b.starts_at) ?? far),
    prize: (a: Item, b: Item) => (b.prize_usd ?? 0) - (a.prize_usd ?? 0),
    newest: (a: Item, b: Item) => (b.first_seen_at ?? "").localeCompare(a.first_seen_at ?? ""),
    popular: (a: Item, b: Item) => (b.participants ?? 0) - (a.participants ?? 0),
    deadline: (a: Item, b: Item) => (nextDeadline(a, now) ?? far) - (nextDeadline(b, now) ?? far),
  } as const;
  const key = (sort === "relevance" && !terms.length ? "deadline" : sort in by ? sort : "deadline") as keyof typeof by;
  found.sort((x, y) => by[key](x.item, y.item, x.score, y.score));

  const size = Math.max(1, Math.min(Number(p.get("page_size") ?? 30) || 30, 100));
  const page = Math.max(1, Number(p.get("page") ?? 1) || 1);
  return {
    total: found.length,
    page,
    page_size: size,
    items: found.slice((page - 1) * size, page * size).map((f) => enrich(f.item, now, names)),
  };
}
