import { useMemo, useState, type ReactNode } from "react";
import { fmtMoney } from "../lib/format";
import { STATUS_OPTIONS, type Facets, type Filters, type ListKey } from "../lib/filters";
import type { SourceInfo, Taxonomy } from "../lib/types";
import { StateMap } from "./StateMap";

interface Props {
  filters: Filters;
  setFilters: (patch: Partial<Filters>) => void;
  facets: Facets;
  taxonomy: Taxonomy;
  sources: Record<string, SourceInfo>;
  currency: string;
  fx?: Record<string, number>;
  hiddenCount: number;
  busyCount: number;
}

interface Option {
  value: string;
  label: string;
  count: number;
}

function Section({ title, children, active = 0, open = true }: { title: string; children: ReactNode; active?: number; open?: boolean }) {
  return (
    <details className="nb-section" open={open || active > 0}>
      <summary>
        <span>{title}</span>
        {active > 0 && <span className="nb-active">{active}</span>}
      </summary>
      <div className="nb-body">{children}</div>
    </details>
  );
}

function CheckList({
  name,
  options,
  selected,
  onChange,
  limit = 7,
  searchable = false,
}: {
  name: string;
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
  limit?: number;
  searchable?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = options.filter((o) => o.count > 0 || selected.includes(o.value));
    if (q) list = list.filter((o) => o.label.toLowerCase().includes(q));
    return list;
  }, [options, selected, query]);
  const shown = expanded || query ? visible : visible.slice(0, limit);
  // keep selected values visible even when collapsed
  for (const v of selected) {
    if (!shown.some((o) => o.value === v)) {
      const o = visible.find((x) => x.value === v);
      if (o) shown.push(o);
    }
  }
  const toggle = (v: string) => onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

  return (
    <div className="nb-list">
      {searchable && visible.length > limit && (
        <input
          className="nb-search"
          type="search"
          placeholder={`Find a ${name}`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={`Find a ${name}`}
        />
      )}
      {shown.map((o) => (
        <label key={o.value} className={`nb-row${o.count === 0 ? " is-empty" : ""}`}>
          <input type="checkbox" checked={selected.includes(o.value)} onChange={() => toggle(o.value)} />
          <span className="nb-label">{o.label}</span>
          <span className="nb-count">{o.count.toLocaleString("en-IN")}</span>
        </label>
      ))}
      {shown.length === 0 && <p className="nb-none">Nothing here with the other filters on.</p>}
      {!query && visible.length > limit && (
        <button type="button" className="nb-more" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Show fewer" : `Show all ${visible.length}`}
        </button>
      )}
    </div>
  );
}

function Radios({ name, value, options, onChange }: { name: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <div className="nb-list" role="radiogroup" aria-label={name}>
      {options.map((o) => (
        <label key={`r-${o.value}`} className="nb-row">
          <input type="radio" name={name} checked={value === o.value} onChange={() => onChange(o.value)} />
          <span className="nb-label">{o.label}</span>
        </label>
      ))}
    </div>
  );
}

export function FilterPanel({ filters, setFilters, facets, taxonomy, sources, currency, fx, hiddenCount, busyCount }: Props) {
  const opts = (key: ListKey, labels: Record<string, string> | ((v: string) => string), order: "count" | "label" | string[] = "count"): Option[] => {
    const counts = facets[key];
    const label = typeof labels === "function" ? labels : (v: string) => labels[v] ?? v;
    const values = new Set<string>([...counts.keys(), ...filters[key]]);
    if (Array.isArray(order)) order.forEach((v) => values.add(v));
    const list = [...values].map((v) => ({ value: v, label: label(v), count: counts.get(v) ?? 0 }));
    if (Array.isArray(order)) return list.sort((a, b) => order.indexOf(a.value) - order.indexOf(b.value));
    if (order === "label") return list.sort((a, b) => a.label.localeCompare(b.label));
    return list.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  };

  const hasAny = (key: ListKey) => [...facets[key].values()].some((n) => n > 0);

  const rate = fx?.[currency];
  const money = (usd: number) =>
    currency !== "USD" && rate ? `${fmtMoney(usd, "USD", true)} (≈ ${fmtMoney(usd / rate, currency, true)})` : fmtMoney(usd, "USD", true);

  return (
    <div className="notebook__inner">
      <Section title="Status" active={filters.status.length}>
        <CheckList
          name="status"
          options={STATUS_OPTIONS.map((s) => ({ value: s.key, label: s.label, count: facets.status.get(s.key) ?? 0 }))}
          selected={filters.status}
          onChange={(status) => setFilters({ status })}
        />
      </Section>

      <Section title="Closing within" active={filters.closing ? 1 : 0}>
        <Radios
          name="closing"
          value={filters.closing}
          onChange={(closing) => setFilters({ closing })}
          options={[
            { value: "", label: "Any time" },
            { value: "3", label: "3 days" },
            { value: "7", label: "A week" },
            { value: "14", label: "Two weeks" },
            { value: "30", label: "A month" },
          ]}
        />
      </Section>

      <Section title="Mode" active={filters.mode.length}>
        <CheckList name="mode" options={opts("mode", taxonomy.modes, ["online", "in_person", "hybrid"])} selected={filters.mode} onChange={(mode) => setFilters({ mode })} />
      </Section>

      <Section title="Where" active={filters.region.length + filters.country.length + filters.state.length + filters.city.length}>
        <CheckList name="region" options={opts("region", (v) => v)} selected={filters.region} onChange={(region) => setFilters({ region })} limit={6} />
        <p className="nb-sub">Country</p>
        <CheckList name="country" options={opts("country", (v) => v)} selected={filters.country} onChange={(country) => setFilters({ country })} limit={6} searchable />
        {(hasAny("state") || filters.state.length > 0) && (
          <>
            <p className="nb-sub">State in India</p>
            <StateMap
              counts={facets.state}
              selected={filters.state}
              onToggle={(s) => setFilters({ state: filters.state.includes(s) ? filters.state.filter((x) => x !== s) : [...filters.state, s] })}
            />
            <p className="nb-hint">Tap a state, or tick it below. Numbers are hackathons there.</p>
            <CheckList name="state" options={opts("state", (v) => v)} selected={filters.state} onChange={(state) => setFilters({ state })} limit={6} searchable />
          </>
        )}
        {(hasAny("city") || filters.city.length > 0) && (
          <>
            <p className="nb-sub">City</p>
            <CheckList name="city" options={opts("city", (v) => v)} selected={filters.city} onChange={(city) => setFilters({ city })} limit={6} searchable />
          </>
        )}
      </Section>

      <Section title="Platform" active={filters.source.length}>
        <CheckList
          name="platform"
          options={opts("source", (v) => sources[v]?.name ?? v)}
          selected={filters.source}
          onChange={(source) => setFilters({ source })}
          limit={8}
          searchable
        />
      </Section>

      <Section title="Theme" active={filters.theme.length}>
        <CheckList name="theme" options={opts("theme", taxonomy.themes)} selected={filters.theme} onChange={(theme) => setFilters({ theme })} limit={8} searchable />
      </Section>

      <Section title="Prize pool" active={filters.prize ? 1 : 0}>
        <Radios
          name="prize"
          value={filters.prize}
          onChange={(prize) => setFilters({ prize })}
          options={[
            { value: "", label: "Any, or none" },
            { value: "any", label: "Has prizes listed" },
            { value: "1000", label: `${money(1000)} or more` },
            { value: "10000", label: `${money(10000)} or more` },
            { value: "50000", label: `${money(50000)} or more` },
          ]}
        />
      </Section>

      <Section title="Format" active={filters.kind.length} open={false}>
        <CheckList
          name="format"
          options={opts("kind", taxonomy.kinds, Object.keys(taxonomy.kinds))}
          selected={filters.kind}
          onChange={(kind) => setFilters({ kind })}
        />
      </Section>

      <Section title="Built for" active={filters.audience.length} open={false}>
        <CheckList name="audience" options={opts("audience", taxonomy.audiences)} selected={filters.audience} onChange={(audience) => setFilters({ audience })} />
      </Section>

      <Section title="Starts between" active={filters.from || filters.to ? 1 : 0} open={false}>
        <div className="nb-dates">
          <label>
            <span>From</span>
            <input className="field" type="date" value={filters.from} max={filters.to || undefined} onChange={(e) => setFilters({ from: e.target.value })} />
          </label>
          <label>
            <span>To</span>
            <input className="field" type="date" value={filters.to} min={filters.from || undefined} onChange={(e) => setFilters({ to: e.target.value })} />
          </label>
        </div>
      </Section>

      <Section title="My team size" active={filters.team ? 1 : 0} open={false}>
        <div className="nb-seg" role="radiogroup" aria-label="My team size">
          {[
            ["", "Any"],
            ["1", "Solo"],
            ["2", "2"],
            ["3", "3"],
            ["4", "4"],
            ["5", "5+"],
          ].map(([v, l]) => (
            <button key={v || "any"} type="button" role="radio" aria-checked={filters.team === v} className={filters.team === v ? "is-on" : ""} onClick={() => setFilters({ team: v })}>
              {l}
            </button>
          ))}
        </div>
        <p className="nb-hint">Hides events whose team limits rule your team out.</p>
      </Section>

      <Section title="Only show" active={[filters.beginner, filters.free, filters.travel, filters.fresh, filters.hiring, filters.busy].filter(Boolean).length}>
        <div className="nb-list">
          {(
            [
              ["beginner", "Beginner-friendly"],
              ["free", "Free to enter"],
              ["travel", "Travel reimbursed"],
              ["fresh", "Posted in the last week"],
              ["hiring", "Offers jobs or internships"],
              ...(busyCount > 0 ? ([["busy", "Clear of my busy dates"]] as const) : []),
            ] as const
          ).map(([k, l]) => (
            <label key={k} className="nb-row">
              <input type="checkbox" checked={filters[k]} onChange={(e) => setFilters({ [k]: e.target.checked })} />
              <span className="nb-label">{l}</span>
              <span className="nb-count">{(facets.flags[k] ?? 0).toLocaleString("en-IN")}</span>
            </label>
          ))}
        </div>
      </Section>

      {hiddenCount > 0 && (
        <label className="nb-row nb-hidden">
          <input type="checkbox" checked={filters.hidden} onChange={(e) => setFilters({ hidden: e.target.checked })} />
          <span className="nb-label">Show only the {hiddenCount} I hid</span>
        </label>
      )}
    </div>
  );
}
