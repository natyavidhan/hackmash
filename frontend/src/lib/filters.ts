import { DAY, lifecycle, nextDeadline } from "./lifecycle";
import type { Hackathon } from "./types";

export type SortKey = "deadline" | "starts" | "prize" | "newest" | "popular" | "relevance";
export type ViewKey = "board" | "list" | "calendar" | "map";

export interface Filters {
  q: string;
  status: string[]; // live | soon
  mode: string[];
  source: string[];
  theme: string[];
  region: string[];
  country: string[];
  state: string[];
  city: string[];
  kind: string[];
  audience: string[];
  prize: string; // "" | "any" | min USD
  closing: string; // "" | days until next deadline
  from: string; // yyyy-mm-dd, start date lower bound
  to: string;
  beginner: boolean;
  free: boolean;
  fresh: boolean;
  travel: boolean;
  hiring: boolean;
  busy: boolean; // hide events that overlap my busy dates
  team: string; // "" | my team size
  sort: SortKey;
  view: ViewKey;
  hidden: boolean;
}

export const LIST_KEYS = ["status", "mode", "source", "theme", "region", "country", "state", "city", "kind", "audience"] as const;
export type ListKey = (typeof LIST_KEYS)[number];
const BOOL_KEYS = ["beginner", "free", "fresh", "travel", "hiring", "busy", "hidden"] as const;
type BoolKey = (typeof BOOL_KEYS)[number];
const TEXT_KEYS = ["q", "prize", "closing", "from", "to", "team"] as const;

export const SORTS: { key: SortKey; label: string }[] = [
  { key: "deadline", label: "Closing soonest" },
  { key: "starts", label: "Starting soonest" },
  { key: "prize", label: "Biggest prize" },
  { key: "newest", label: "Newly posted" },
  { key: "popular", label: "Most registrations" },
  { key: "relevance", label: "Best match" },
];

// The board only pins up events you can still register for, so "open" is not a choice.
export const STATUS_OPTIONS: { key: string; label: string }[] = [
  { key: "live", label: "Happening now" },
  { key: "soon", label: "Not started yet" },
];

/**
 * Is it on the board? Only while registration is open. A search also finds
 * events under way whose registration has closed; everything else (closed and
 * not started, ended) is reachable only by its link.
 */
export function isListed(h: Hackathon, now: number, searching: boolean): boolean {
  const { status, regOpen } = lifecycle(h, now);
  return regOpen || (searching && status === "live");
}

export const DEFAULT_FILTERS: Filters = {
  q: "",
  status: [],
  mode: [],
  source: [],
  theme: [],
  region: [],
  country: [],
  state: [],
  city: [],
  kind: [],
  audience: [],
  prize: "",
  closing: "",
  from: "",
  to: "",
  beginner: false,
  free: false,
  fresh: false,
  travel: false,
  hiring: false,
  busy: false,
  team: "",
  sort: "deadline",
  view: "board",
  hidden: false,
};

export function parseFilters(sp: URLSearchParams): Filters {
  const f: Filters = { ...DEFAULT_FILTERS };
  for (const k of LIST_KEYS) f[k] = sp.get(k)?.split(",").filter(Boolean) ?? [];
  // old links and pinned searches may still say status=open or status=ended
  f.status = f.status.filter((s) => STATUS_OPTIONS.some((o) => o.key === s));
  for (const k of TEXT_KEYS) f[k] = sp.get(k) ?? "";
  for (const k of BOOL_KEYS) f[k] = sp.get(k) === "1";
  const sort = sp.get("sort") as SortKey | null;
  f.sort = sort && SORTS.some((s) => s.key === sort) ? sort : f.q ? "relevance" : "deadline";
  const view = sp.get("view") as ViewKey | null;
  f.view = view === "list" || view === "calendar" || view === "map" ? view : "board";
  return f;
}

/** Serialise filters, preserving unrelated params (e.g. the open notice `h`). */
export function filtersToParams(f: Filters, base?: URLSearchParams): URLSearchParams {
  const sp = new URLSearchParams(base);
  for (const k of LIST_KEYS) (f[k].length ? sp.set(k, f[k].join(",")) : sp.delete(k));
  for (const k of TEXT_KEYS) (f[k] ? sp.set(k, f[k]) : sp.delete(k));
  for (const k of BOOL_KEYS) (f[k] ? sp.set(k, "1") : sp.delete(k));
  const defaultSort = f.q ? "relevance" : "deadline";
  f.sort !== defaultSort ? sp.set("sort", f.sort) : sp.delete("sort");
  f.view !== "board" ? sp.set("view", f.view) : sp.delete("view");
  return sp;
}

export function activeFilterCount(f: Filters): number {
  let n = 0;
  for (const k of LIST_KEYS) n += f[k].length;
  for (const k of ["prize", "closing", "team"] as const) if (f[k]) n++;
  if (f.from || f.to) n++;
  for (const k of ["beginner", "free", "fresh", "travel", "hiring", "busy"] as const) if (f[k]) n++;
  return n;
}

export interface FilterContext {
  now: number;
  dismissed: Set<string>;
  terms: string[];
  busy?: { from: number; to: number }[];
}

/** Does the event's run overlap any of the visitor's busy ranges? */
export function overlapsBusy(h: Hackathon, busy: { from: number; to: number }[] | undefined): boolean {
  if (!busy?.length || h.start === undefined) return false;
  const end = h.end && h.end - h.start < 10 * DAY ? h.end : h.start + DAY; // long online events: only the kickoff matters
  return busy.some((b) => h.start! <= b.to && end >= b.from);
}

export function searchTerms(q: string): string[] {
  return q
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}

const termMatchers = new Map<string, (text: string) => boolean>();

/** Short terms ("ai", "ar", "ml") match at the start of a word, so "ai" doesn't hit "Chennai". */
export function termMatcher(term: string): (text: string) => boolean {
  let m = termMatchers.get(term);
  if (!m) {
    if (term.length <= 3) {
      const rx = new RegExp(`(^|[^\\p{L}\\p{N}])${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "u");
      m = (text) => rx.test(text);
    } else {
      m = (text) => text.includes(term);
    }
    termMatchers.set(term, m);
  }
  return m;
}

type Dim = ListKey | BoolKey | "q" | "prize" | "closing" | "dates" | "team";

function statusBuckets(h: Hackathon, now: number): Set<string> {
  const { status } = lifecycle(h, now);
  const b = new Set<string>();
  if (status === "live") b.add("live");
  if (h.start !== undefined ? h.start > now : status === "open" || status === "upcoming") b.add("soon");
  return b;
}

const PREDICATES: Record<Dim, (h: Hackathon, f: Filters, c: FilterContext) => boolean> = {
  q: (h, _f, c) => c.terms.every((t) => termMatcher(t)(h.search)),
  status: (h, f, c) => {
    if (!isListed(h, c.now, c.terms.length > 0)) return false;
    if (!f.status.length) return true;
    const b = statusBuckets(h, c.now);
    return f.status.some((s) => b.has(s));
  },
  mode: (h, f) => !f.mode.length || (!!h.mode && f.mode.includes(h.mode)),
  source: (h, f) => !f.source.length || h.allSources.some((s) => f.source.includes(s)),
  theme: (h, f) => !f.theme.length || (h.themes ?? []).some((t) => f.theme.includes(t)),
  region: (h, f) => !f.region.length || (!!h.region && f.region.includes(h.region)),
  country: (h, f) => !f.country.length || (!!h.country && f.country.includes(h.country)),
  state: (h, f) => !f.state.length || (!!h.state && f.state.includes(h.state)),
  city: (h, f) => !f.city.length || (!!h.city && f.city.includes(h.city)),
  kind: (h, f) => !f.kind.length || f.kind.includes(h.kind ?? "hackathon"),
  audience: (h, f) => !f.audience.length || (h.audience ?? []).some((a) => f.audience.includes(a)),
  prize: (h, f) => {
    if (!f.prize) return true;
    if (f.prize === "any") return (h.prize_usd ?? 0) > 0 || !!h.prize_text;
    return (h.prize_usd ?? 0) >= Number(f.prize);
  },
  closing: (h, f, c) => {
    if (!f.closing) return true;
    const nd = nextDeadline(h, c.now);
    return !!nd && nd.kind !== "start" && nd.at - c.now <= Number(f.closing) * DAY;
  },
  dates: (h, f) => {
    if (!f.from && !f.to) return true;
    if (h.start === undefined) return false;
    if (f.from && h.start < Date.parse(`${f.from}T00:00:00`)) return false;
    if (f.to && h.start > Date.parse(`${f.to}T23:59:59`)) return false;
    return true;
  },
  team: (h, f) => {
    if (!f.team) return true;
    const n = Number(f.team);
    return (h.team_size_min ?? 1) <= n && (h.team_size_max ?? 99) >= n;
  },
  beginner: (h, f) => !f.beginner || !!h.beginner_friendly,
  free: (h, f) => !f.free || !h.registration_fee,
  fresh: (h, f, c) => !f.fresh || (!!h.firstSeen && c.now - h.firstSeen <= 7 * DAY),
  travel: (h, f) => !f.travel || !!h.travel_reimbursement,
  hiring: (h, f) => !f.hiring || !!h.hiring,
  busy: (h, f, c) => !f.busy || !overlapsBusy(h, c.busy),
  hidden: (h, f, c) => (f.hidden ? c.dismissed.has(h.id) : !c.dismissed.has(h.id)),
};

const DIMS = Object.keys(PREDICATES) as Dim[];

export function matches(h: Hackathon, f: Filters, c: FilterContext, skip?: Dim): boolean {
  for (const d of DIMS) if (d !== skip && !PREDICATES[d](h, f, c)) return false;
  return true;
}

export function applyFilters(items: Hackathon[], f: Filters, c: FilterContext): Hackathon[] {
  return items.filter((h) => matches(h, f, c));
}

export type Facets = Record<ListKey, Map<string, number>> & { flags: Record<string, number> };

/** Counts per facet value, each computed with every *other* filter applied. */
export function facetCounts(items: Hackathon[], f: Filters, c: FilterContext): Facets {
  const out = { flags: {} } as Facets;
  for (const key of LIST_KEYS) {
    const counts = new Map<string, number>();
    for (const h of items) {
      if (!matches(h, f, c, key)) continue;
      const values =
        key === "status"
          ? [...statusBuckets(h, c.now)]
          : key === "source"
            ? h.allSources
            : key === "theme"
              ? (h.themes ?? [])
              : key === "audience"
                ? (h.audience ?? [])
                : key === "kind"
                  ? [h.kind ?? "hackathon"]
                  : [h[key as "mode" | "region" | "country" | "state" | "city"]].filter(Boolean);
      for (const v of new Set(values)) counts.set(v as string, (counts.get(v as string) ?? 0) + 1);
    }
    out[key] = counts;
  }
  for (const flag of ["beginner", "free", "fresh", "travel", "hiring", "busy"] as const) {
    let n = 0;
    const on = { ...f, [flag]: true };
    for (const h of items) if (matches(h, on, c)) n++;
    out.flags[flag] = n;
  }
  return out;
}

export function sortItems(items: Hackathon[], f: Filters, c: FilterContext): Hackathon[] {
  const far = Number.MAX_SAFE_INTEGER;
  const copy = [...items];
  const byDeadline = (a: Hackathon, b: Hackathon) =>
    (nextDeadline(a, c.now)?.at ?? far) - (nextDeadline(b, c.now)?.at ?? far) || (a.start ?? far) - (b.start ?? far);
  switch (f.sort) {
    case "starts":
      return copy.sort((a, b) => (a.start ?? far) - (b.start ?? far) || byDeadline(a, b));
    case "prize":
      return copy.sort((a, b) => (b.prize_usd ?? -1) - (a.prize_usd ?? -1) || byDeadline(a, b));
    case "newest":
      return copy.sort((a, b) => (b.firstSeen ?? 0) - (a.firstSeen ?? 0) || byDeadline(a, b));
    case "popular":
      return copy.sort((a, b) => (b.participants ?? -1) - (a.participants ?? -1) || byDeadline(a, b));
    case "relevance": {
      if (!c.terms.length) return copy.sort(byDeadline);
      const score = (h: Hackathon) => {
        const title = h.title.toLowerCase();
        return c.terms.reduce((s, t) => s + (title.includes(t) ? 4 : 0) + ((h.organizer ?? "").toLowerCase().includes(t) ? 2 : 0) + 1, 0);
      };
      return copy.sort((a, b) => score(b) - score(a) || byDeadline(a, b));
    }
    default:
      return copy.sort(byDeadline);
  }
}
