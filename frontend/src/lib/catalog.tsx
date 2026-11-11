import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { Catalog, Hackathon, RawItem, SourceInfo, Taxonomy } from "./types";

/** Every current hackathon's card. In production the Worker builds it from the database. */
const FEED_URL = "/api/catalog";
const STALE_AFTER = 20 * 60_000; // re-check when the tab comes back after this long
const REFRESH_EVERY = 30 * 60_000; // and this often while it stays open

const ts = (v?: string) => {
  if (!v) return undefined;
  const t = Date.parse(v);
  return Number.isNaN(t) ? undefined : t;
};

function derive(raw: RawItem, names: Record<string, string>, tax: Taxonomy): Hackathon {
  const sourceName = names[raw.source] ?? raw.source;
  const allSources = [raw.source, ...(raw.also_on ?? []).map((l) => l.source)];
  const themeLabels = (raw.themes ?? []).map((t) => tax.themes[t] ?? t);
  const search = [
    raw.title,
    raw.organizer,
    raw.tagline,
    raw.location,
    raw.city,
    raw.country,
    raw.region,
    sourceName,
    ...(raw.also_on ?? []).map((l) => names[l.source] ?? l.source),
    raw.kind ? tax.kinds[raw.kind] : "",
    raw.mode ? tax.modes[raw.mode] : "",
    ...(raw.tags ?? []),
    ...themeLabels,
  ]
    .filter(Boolean)
    .join(" • ")
    .toLowerCase();
  return {
    ...raw,
    sourceName,
    allSources,
    start: ts(raw.starts_at),
    end: ts(raw.ends_at),
    regOpens: ts(raw.registration_opens_at),
    regDeadline: ts(raw.registration_deadline),
    subDeadline: ts(raw.submission_deadline),
    firstSeen: ts(raw.first_seen_at),
    search,
  };
}

type LoadState = "loading" | "ready" | "error";

interface CatalogContextValue {
  state: LoadState;
  error?: string;
  catalog?: Catalog;
  items: Hackathon[];
  byId: Map<string, Hackathon>;
  sources: Record<string, SourceInfo>;
  taxonomy: Taxonomy;
  generatedAt?: number;
  reload: () => void;
}

const EMPTY_TAX: Taxonomy = { themes: {}, kinds: {}, audiences: {}, modes: {}, regions: [] };

const CatalogContext = createContext<CatalogContextValue | null>(null);

export function CatalogProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string>();
  const loadedAt = useRef(0);
  const version = useRef<string | undefined>(undefined);

  const load = useCallback(async (background = false) => {
    if (!background) setState((s) => (s === "ready" ? s : "loading"));
    try {
      // revalidate every time: an unchanged board costs one tiny 304
      const res = await fetch(FEED_URL, { headers: { Accept: "application/json" }, cache: "no-cache" });
      if (res.status === 503) throw new Error("The board is being put up for the first time. Give it a minute and retry.");
      if (!res.ok) throw new Error(`The server answered ${res.status}.`);
      const data = (await res.json()) as Catalog;
      loadedAt.current = Date.now();
      const v = data.data_version ?? data.generated_at;
      if (v !== version.current) {
        version.current = v;
        setCatalog(data);
      }
      setState("ready");
      setError(undefined);
    } catch (e) {
      if (!background) {
        setError(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    }
  }, []);

  useEffect(() => {
    void load();
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - loadedAt.current > STALE_AFTER) void load(true);
    };
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, REFRESH_EVERY);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, [load]);

  const value = useMemo<CatalogContextValue>(() => {
    const taxonomy = catalog?.taxonomy ?? EMPTY_TAX;
    const sources: Record<string, SourceInfo> = {};
    for (const s of catalog?.sources ?? []) sources[s.key] = s;
    const names = Object.fromEntries(Object.values(sources).map((s) => [s.key, s.name]));
    const items = (catalog?.items ?? []).map((r) => derive(r, names, taxonomy));
    const byId = new Map<string, Hackathon>();
    for (const h of items) {
      byId.set(h.id, h);
      for (const alt of h.also_on ?? []) if (!byId.has(alt.id)) byId.set(alt.id, h);
    }
    return {
      state,
      error,
      catalog,
      items,
      byId,
      sources,
      taxonomy,
      generatedAt: catalog ? Date.parse(catalog.generated_at) : undefined,
      reload: () => void load(),
    };
  }, [catalog, state, error, load]);

  return <CatalogContext.Provider value={value}>{children}</CatalogContext.Provider>;
}

export function useCatalog(): CatalogContextValue {
  const ctx = useContext(CatalogContext);
  if (!ctx) throw new Error("useCatalog outside CatalogProvider");
  return ctx;
}

/** A clock that ticks every minute so countdowns and statuses stay true. */
export function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

// -- listings fetched one by one ------------------------------------------------------
// The feed carries what the board shows. Closed and ended events (opened from a
// link or from My tabs) and the long text of any notice are fetched on demand.

const remote = new Map<string, RawItem | null>(); // id (or merged id) -> full listing; null = gone
const pending = new Set<string>();
const listeners = new Set<() => void>();
let remoteVersion = 0;

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
const snapshot = () => remoteVersion;

async function fetchListings(ids: string[]): Promise<void> {
  const want = [...new Set(ids)].filter((id) => !remote.has(id) && !pending.has(id));
  if (!want.length) return;
  for (const id of want) pending.add(id);
  try {
    if (want.length === 1) {
      const res = await fetch(`/api/hackathons/${encodeURIComponent(want[0])}`, { headers: { Accept: "application/json" } });
      if (res.status === 404) remote.set(want[0], null);
      else if (res.ok) remote.set(want[0], (await res.json()) as RawItem);
    } else {
      for (let i = 0; i < want.length; i += 100) {
        const batch = want.slice(i, i + 100);
        const res = await fetch(`/api/hackathons?ids=${encodeURIComponent(batch.join(","))}`, { headers: { Accept: "application/json" } });
        if (!res.ok) continue;
        const found = ((await res.json()) as { items: RawItem[] }).items;
        for (const id of batch) {
          remote.set(id, found.find((r) => r.id === id || (r.also_on ?? []).some((l) => l.id === id)) ?? null);
        }
      }
    }
  } catch {
    // offline: leave them unknown so a later visit retries
  } finally {
    for (const id of want) pending.delete(id);
    remoteVersion++;
    for (const l of listeners) l();
  }
}

/**
 * Listings by id for ids that are not on the board: fetched from the API.
 * The map holds an id once its answer is in (null: it has come down).
 */
export function useOffBoard(ids: string[]): Map<string, Hackathon | null> {
  const { byId, sources, taxonomy, state } = useCatalog();
  const version = useSyncExternalStore(subscribe, snapshot);
  const key = ids.filter((id) => !byId.has(id)).join(",");
  useEffect(() => {
    if (state === "ready" && key) void fetchListings(key.split(","));
  }, [key, state]);
  return useMemo(() => {
    const out = new Map<string, Hackathon | null>();
    if (!key) return out;
    const names = Object.fromEntries(Object.values(sources).map((s) => [s.key, s.name]));
    for (const id of key.split(",")) {
      if (!remote.has(id)) continue;
      const raw = remote.get(id);
      out.set(id, raw ? derive(raw, names, taxonomy) : null);
    }
    return out;
  }, [key, version, sources, taxonomy]); // `version` bumps when answers arrive
}

/** The listing with its long text (description, eligibility, images), fetched if the feed left it out. */
export function useFullListing(h?: Hackathon): Hackathon | undefined {
  const version = useSyncExternalStore(subscribe, snapshot);
  const id = h?.id;
  const needed = !!h && h.description === undefined && !remote.has(h.id);
  useEffect(() => {
    if (needed && id) void fetchListings([id]);
  }, [needed, id]);
  return useMemo(() => {
    const full = h ? remote.get(h.id) : undefined;
    if (!h || !full) return h;
    return { ...h, description: full.description, eligibility: full.eligibility, image_url: full.image_url, logo_url: full.logo_url };
  }, [h, version]); // `version` bumps when answers arrive
}
