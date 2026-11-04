import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Catalog, Hackathon, RawItem, SourceInfo, Taxonomy } from "./types";

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

const STALE_AFTER = 20 * 60_000;

export function CatalogProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string>();
  const loadedAt = useRef(0);

  const load = useCallback(async (background = false) => {
    if (!background) setState((s) => (s === "ready" ? s : "loading"));
    try {
      // a static file in production (CDN-cached, no server work per visit); FastAPI serves it in development
      const res = await fetch("/data/catalog.json", { headers: { Accept: "application/json" } });
      if (res.status === 503) throw new Error("The board is being put up for the first time. Give it a minute and retry.");
      if (!res.ok) throw new Error(`The server answered ${res.status}.`);
      const data = (await res.json()) as Catalog;
      setCatalog(data);
      setState("ready");
      setError(undefined);
      loadedAt.current = Date.now();
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
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
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
