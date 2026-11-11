import { Calendar, LayoutGrid, List, Pin, Search, SlidersHorizontal, X } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CalendarView } from "../components/CalendarView";
import { FilterPanel } from "../components/FilterPanel";
import { ListView } from "../components/ListView";
import { NoticeCard } from "../components/NoticeCard";
import { useCatalog, useNow } from "../lib/catalog";
import {
  activeFilterCount,
  applyFilters,
  DEFAULT_FILTERS,
  facetCounts,
  filtersToParams,
  isListed,
  parseFilters,
  searchTerms,
  SORTS,
  sortItems,
  STATUS_OPTIONS,
  type Filters,
  type ViewKey,
} from "../lib/filters";
import { fmtMoney, plural } from "../lib/format";
import { DAY, HOUR } from "../lib/lifecycle";
import { useMediaQuery } from "../lib/media";
import { busyRanges, currencyPref, previousVisit, tracker, useStore } from "../lib/tracker";

const PAGE = 48;

function busyClash(h: { start?: number; end?: number }, busy: { from: number; to: number; label: string }[]): string | undefined {
  if (!busy.length || h.start === undefined) return undefined;
  const end = h.end && h.end - h.start < 10 * DAY ? h.end : h.start + DAY;
  return busy.find((b) => h.start! <= b.to && end >= b.from)?.label;
}
const eq = (a: string[], b: string[]) => a.length === b.length && a.every((v) => b.includes(v));

export function ExplorePage() {
  const { state, error, items, taxonomy, sources, catalog, reload } = useCatalog();
  const store = useStore();
  const now = useNow();
  const [sp, setSp] = useSearchParams();
  const filters = useMemo(() => parseFilters(sp), [sp]);
  const currency = currencyPref(store);
  const fx = catalog?.fx;
  const [limit, setLimit] = useState(PAGE);
  const [sheetOpen, setSheetOpen] = useState(false);
  const sheetRef = useRef<HTMLDialogElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const setFilters = useCallback(
    (patch: Partial<Filters>, replace = false) => {
      const next = { ...filters, ...patch };
      if ("q" in patch && !("sort" in patch) && patch.q && filters.sort === "deadline" && !sp.get("sort")) next.sort = "relevance";
      if ("q" in patch && !("sort" in patch) && !patch.q && filters.sort === "relevance") next.sort = "deadline";
      setSp(filtersToParams(next, sp), { replace });
    },
    [filters, sp, setSp],
  );

  // Search box. What you type is the truth: results follow at once (at low
  // priority, so typing never stalls) and the address bar catches up after a
  // pause, for sharing and the back button. The box only takes a value from the
  // address when something else changed it (back button, a pinned search, Clear
  // all), never from our own catching up, which used to swallow fast keystrokes.
  const [q, setQ] = useState(filters.q);
  const pushedQ = useRef(filters.q);
  useEffect(() => {
    if (filters.q === pushedQ.current) return;
    pushedQ.current = filters.q;
    setQ(filters.q);
  }, [filters.q]);
  const pushQ = useCallback(
    (value: string) => {
      if (value === pushedQ.current) return;
      pushedQ.current = value;
      setFilters({ q: value }, true);
    },
    [setFilters],
  );
  useEffect(() => {
    if (q === pushedQ.current) return;
    const t = window.setTimeout(() => pushQ(q), 450);
    return () => window.clearTimeout(t);
  }, [q, pushQ]);
  const typed = useDeferredValue(q);
  // the filters as shown: the address's, with the query as typed
  const view = useMemo(() => {
    if (typed === filters.q) return filters;
    const p = new URLSearchParams(sp);
    if (typed) p.set("q", typed);
    else p.delete("q");
    return parseFilters(p);
  }, [filters, sp, typed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) && !el.isContentEditable) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => setLimit(PAGE), [sp, typed]);

  useEffect(() => {
    const d = sheetRef.current;
    if (!d) return;
    if (sheetOpen && !d.open) d.showModal();
    if (!sheetOpen && d.open) d.close();
  }, [sheetOpen]);

  const dismissed = useMemo(() => new Set(store.dismissed), [store.dismissed]);
  const busy = useMemo(() => busyRanges(store), [store]);
  const ctx = useMemo(() => ({ now, dismissed, terms: searchTerms(view.q), busy }), [now, dismissed, view.q, busy]);
  const results = useMemo(() => sortItems(applyFilters(items, view, ctx), view, ctx), [items, view, ctx]);
  const facets = useMemo(() => facetCounts(items, view, ctx), [items, view, ctx]);
  const active = activeFilterCount(view);
  const boardCount = useMemo(() => items.filter((h) => isListed(h, now, false)).length, [items, now]);
  // the first import is not "new"; after that, new = first pinned since your last visit
  const epoch = useMemo(() => items.reduce((m, h) => Math.min(m, h.firstSeen ?? Infinity), Infinity), [items]);
  const newSince = Math.max(previousVisit ?? now - 3 * DAY, epoch + 12 * HOUR);
  const narrow = useMediaQuery("(max-width: 720px)");

  const rate = fx?.[currency];
  const bigPrize = currency !== "USD" && rate ? fmtMoney(10000 / rate, currency, true) : "$10k";

  const slips: { key: string; label: string; on: boolean; toggle: () => void }[] = [
    { key: "week", label: "Closing this week", on: filters.closing === "7", toggle: () => setFilters({ closing: filters.closing === "7" ? "" : "7" }) },
    { key: "online", label: "Online", on: eq(filters.mode, ["online"]), toggle: () => setFilters({ mode: eq(filters.mode, ["online"]) ? [] : ["online"] }) },
    { key: "irl", label: "In person", on: eq(filters.mode, ["in_person", "hybrid"]), toggle: () => setFilters({ mode: eq(filters.mode, ["in_person", "hybrid"]) ? [] : ["in_person", "hybrid"] }) },
    { key: "india", label: "In India", on: eq(filters.country, ["India"]), toggle: () => setFilters({ country: eq(filters.country, ["India"]) ? [] : ["India"] }) },
    { key: "beginner", label: "Beginner-friendly", on: filters.beginner, toggle: () => setFilters({ beginner: !filters.beginner }) },
    { key: "big", label: `Prizes over ${bigPrize}`, on: filters.prize === "10000", toggle: () => setFilters({ prize: filters.prize === "10000" ? "" : "10000" }) },
    { key: "free", label: "Free entry", on: filters.free, toggle: () => setFilters({ free: !filters.free }) },
    { key: "fresh", label: "New this week", on: filters.fresh, toggle: () => setFilters({ fresh: !filters.fresh }) },
  ];

  // removable chips for every active filter value
  const chips: { key: string; label: string; remove: () => void }[] = [];
  const listChip = (k: "status" | "mode" | "source" | "theme" | "region" | "country" | "kind" | "audience", label: (v: string) => string) =>
    filters[k].forEach((v) => chips.push({ key: `${k}:${v}`, label: label(v), remove: () => setFilters({ [k]: filters[k].filter((x) => x !== v) }) }));
  listChip("status", (v) => STATUS_OPTIONS.find((s) => s.key === v)?.label ?? v);
  listChip("mode", (v) => taxonomy.modes[v] ?? v);
  listChip("source", (v) => sources[v]?.name ?? v);
  listChip("theme", (v) => taxonomy.themes[v] ?? v);
  listChip("region", (v) => v);
  listChip("country", (v) => v);
  listChip("kind", (v) => taxonomy.kinds[v] ?? v);
  listChip("audience", (v) => taxonomy.audiences[v] ?? v);
  if (filters.closing) chips.push({ key: "closing", label: `Closing within ${filters.closing} days`, remove: () => setFilters({ closing: "" }) });
  if (filters.prize) chips.push({ key: "prize", label: filters.prize === "any" ? "Has prizes" : `Prizes over $${Number(filters.prize) / 1000}k`, remove: () => setFilters({ prize: "" }) });
  if (filters.from || filters.to) chips.push({ key: "dates", label: `Starts ${filters.from || "…"} to ${filters.to || "…"}`, remove: () => setFilters({ from: "", to: "" }) });
  if (filters.team) chips.push({ key: "team", label: filters.team === "1" ? "Solo" : `Team of ${filters.team}`, remove: () => setFilters({ team: "" }) });
  if (filters.beginner) chips.push({ key: "beginner", label: "Beginner-friendly", remove: () => setFilters({ beginner: false }) });
  if (filters.free) chips.push({ key: "free", label: "Free entry", remove: () => setFilters({ free: false }) });
  if (filters.travel) chips.push({ key: "travel", label: "Travel reimbursed", remove: () => setFilters({ travel: false }) });
  if (filters.fresh) chips.push({ key: "fresh", label: "New this week", remove: () => setFilters({ fresh: false }) });
  if (filters.hiring) chips.push({ key: "hiring", label: "Jobs or internships", remove: () => setFilters({ hiring: false }) });
  if (filters.busy) chips.push({ key: "busy", label: "Avoiding my busy dates", remove: () => setFilters({ busy: false }) });
  if (filters.hidden) chips.push({ key: "hidden", label: "Hidden notices", remove: () => setFilters({ hidden: false }) });

  const clearAll = () => setSp(filtersToParams({ ...DEFAULT_FILTERS, view: filters.view }, new URLSearchParams(sp.get("h") ? { h: sp.get("h")! } : {})));

  const currentQuery = (() => {
    const p = filtersToParams(view);
    p.delete("view");
    p.delete("h");
    return p.toString();
  })();
  const isPinned = store.pinned.some((p) => p.query === currentQuery);
  const pinThis = () => {
    const name = [view.q && `"${view.q}"`, ...chips.slice(0, 3).map((c) => c.label)].filter(Boolean).join(", ") || "My search";
    tracker.pinSearch(name.length > 60 ? `${name.slice(0, 58)}…` : name, currentQuery);
  };

  const setView = (view: ViewKey) => setFilters({ view });
  const panel = (
    <FilterPanel
      filters={view}
      setFilters={(p) => setFilters(p)}
      facets={facets}
      taxonomy={taxonomy}
      sources={sources}
      currency={currency}
      fx={fx}
      hiddenCount={store.dismissed.length}
      busyCount={store.busy.length}
    />
  );

  return (
    <main id="main" className="page explore">
      <h1 className="visually-hidden">Every hackathon, one board</h1>
      <section className="searchbar" aria-label="Search and sort">
        <label className="searchstrip paper">
          <Search size={20} aria-hidden="true" className="searchstrip__icon" />
          <span className="visually-hidden">Search hackathons</span>
          <input
            ref={searchRef}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              pushQ(q);
              if (narrow) e.currentTarget.blur(); // put the phone keyboard away to show results
            }}
            placeholder={!boardCount ? "Search hackathons" : narrow ? `Search ${plural(boardCount, "hackathon")}` : `Search ${plural(boardCount, "hackathon")}: try “AI”, “Bengaluru”, “web3 online”`}
            enterKeyHint="search"
            autoComplete="off"
            spellCheck={false}
          />
          {q ? (
            <button type="button" className="icon-btn" onClick={() => setQ("")} aria-label="Clear search">
              <X size={18} />
            </button>
          ) : (
            <span className="kbd searchstrip__kbd" aria-hidden="true">
              /
            </span>
          )}
        </label>
        <div className="searchbar__tools">
          <button type="button" className="btn filters-toggle" onClick={() => setSheetOpen(true)}>
            <SlidersHorizontal size={16} aria-hidden="true" /> <span className="filters-toggle__label">Filters</span>{active > 0 && <span className="filters-toggle__n">{active}</span>}
          </button>
          <label className="sortpick">
            <span className="visually-hidden">Sort by</span>
            <select
              className="field"
              value={view.sort}
              onChange={(e) => {
                pushedQ.current = q; // the query as typed goes along with the new order
                setFilters({ q, sort: e.target.value as Filters["sort"] });
              }}
            >
              {SORTS.filter((s) => s.key !== "relevance" || view.q).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <div className="viewpick" role="radiogroup" aria-label="Layout">
            {(
              [
                ["board", LayoutGrid, "Board"],
                ["list", List, "List"],
                ["calendar", Calendar, "Calendar"],
              ] as const
            ).map(([key, Icon, label]) => (
              <button key={key} type="button" role="radio" aria-checked={filters.view === key} className={filters.view === key ? "is-on" : ""} onClick={() => setView(key)} title={label}>
                <Icon size={16} aria-hidden="true" />
                <span className="viewpick__label">{label}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="slips" role="group" aria-label="Quick filters">
        {slips.map((s) => (
          <button key={s.key} type="button" className={`slip${s.on ? " is-on" : ""}`} aria-pressed={s.on} onClick={s.toggle}>
            <span className={`pin ${s.on ? "pin--blue" : ""} slip__pin`} aria-hidden="true" />
            {s.label}
          </button>
        ))}
      </div>

      {store.pinned.length > 0 && (
        <div className="pinned" aria-label="Your pinned searches">
          <span className="pinned__label hand">your pinned searches →</span>
          {store.pinned.map((p) => (
            <span key={p.id} className={`pinned__item${p.query === currentQuery ? " is-on" : ""}`}>
              <Link to={{ search: p.query ? `?${p.query}` : "" }}>{p.name}</Link>
              <button type="button" onClick={() => tracker.unpinSearch(p.id)} aria-label={`Unpin ${p.name}`}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="explore__body">
        <aside className="notebook paper paper-scroll" aria-label="Filters">
          {panel}
        </aside>

        <section className="results" aria-label="Results" aria-busy={state === "loading"}>
          <div className="results__bar">
            <p className="results__count" aria-live="polite">
              {state === "ready" ? (
                <>
                  <strong>{plural(results.length, "hackathon")}</strong>
                  {active > 0 || view.q ? " match" : " on the board"}
                </>
              ) : (
                "Pinning up the board…"
              )}
            </p>
            {chips.length > 0 && (
              <ul className="chips">
                {chips.map((c) => (
                  <li key={c.key}>
                    <button type="button" className="chip" onClick={c.remove} aria-label={`Remove filter: ${c.label}`}>
                      {c.label} <X size={12} aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="results__actions">
              {(active > 0 || view.q) && (
                <>
                  <button type="button" className="btn btn--sm btn--ghost" onClick={clearAll}>
                    Clear all
                  </button>
                  <button type="button" className="btn btn--sm" onClick={pinThis} disabled={isPinned}>
                    <Pin size={14} aria-hidden="true" /> {isPinned ? "Pinned" : "Pin this search"}
                  </button>
                </>
              )}
            </div>
          </div>

          {state === "error" && (
            <div className="board-note paper">
              <span className="pin pin--red board-note__pin" aria-hidden="true" />
              <h2>Couldn’t fetch the board</h2>
              <p>{error}</p>
              <button type="button" className="btn btn--ink" onClick={reload}>
                Try again
              </button>
            </div>
          )}

          {state === "loading" && (
            <div className="notice-grid" aria-hidden="true">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="notice notice--ghost">
                  <span className="pin notice__pin" />
                </div>
              ))}
            </div>
          )}

          {state === "ready" && results.length === 0 && (
            <div className="board-note paper">
              <span className="pin pin--blue board-note__pin" aria-hidden="true" />
              <h2>Nothing on the board matches</h2>
              <p>
                {filters.hidden
                  ? "You haven’t hidden anything that matches these filters."
                  : "Every filter narrows the board. Drop one of these and look again:"}
              </p>
              {chips.length > 0 && (
                <ul className="chips chips--center">
                  {chips.slice(0, 6).map((c) => (
                    <li key={c.key}>
                      <button type="button" className="chip" onClick={c.remove}>
                        {c.label} <X size={12} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <button type="button" className="btn btn--ink" onClick={clearAll}>
                Clear all filters
              </button>
            </div>
          )}

          {state === "ready" && results.length > 0 && filters.view === "board" && (
            <div className="notice-grid">
              {results.slice(0, limit).map((h) => (
                <NoticeCard
                  key={h.id}
                  h={h}
                  now={now}
                  currency={currency}
                  fx={fx}
                  taxonomy={taxonomy}
                  tracked={store.items[h.id]}
                  isNew={!!h.firstSeen && h.firstSeen > newSince}
                  busyClash={busyClash(h, busy)}
                  dismissed={dismissed.has(h.id)}
                />
              ))}
            </div>
          )}

          {state === "ready" && results.length > 0 && filters.view === "list" && (
            <ListView items={results.slice(0, limit * 2)} now={now} currency={currency} fx={fx} tracked={store.items} taxonomy={taxonomy} />
          )}

          {state === "ready" && filters.view === "calendar" && results.length > 0 && <CalendarView items={results} now={now} />}

          {state === "ready" && filters.view !== "calendar" && results.length > (filters.view === "list" ? limit * 2 : limit) && (
            <div className="more">
              <button type="button" className="btn btn--ink" onClick={() => setLimit((l) => l + PAGE * (filters.view === "list" ? 2 : 1))}>
                Show more ({plural(results.length - (filters.view === "list" ? limit * 2 : limit), "notice")} left)
              </button>
            </div>
          )}
        </section>
      </div>

      <dialog
        ref={sheetRef}
        className="filter-sheet"
        onClose={() => setSheetOpen(false)}
        onClick={(e) => {
          if (e.target === e.currentTarget) setSheetOpen(false);
        }}
        aria-label="Filters"
      >
        <div className="filter-sheet__paper paper paper-scroll">
          <div className="filter-sheet__head">
            <h2>Filters</h2>
            <button type="button" className="icon-btn" onClick={() => setSheetOpen(false)} aria-label="Close filters">
              <X size={20} />
            </button>
          </div>
          {sheetOpen && panel}
          <div className="filter-sheet__foot">
            <button type="button" className="btn btn--ghost" onClick={clearAll} disabled={active === 0}>
              Clear all
            </button>
            <button type="button" className="btn btn--ink" onClick={() => setSheetOpen(false)}>
              Show {plural(results.length, "hackathon")}
            </button>
          </div>
        </div>
      </dialog>
    </main>
  );
}
