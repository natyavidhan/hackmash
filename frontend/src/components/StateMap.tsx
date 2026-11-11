import { useEffect, useLayoutEffect, useRef, useState } from "react";

interface MiniMap {
  width: number;
  height: number;
  states: { name: string; d: string; at: number[]; area: number }[];
  outline: string;
}

let loaded: MiniMap | null = null;
const MIN_LABEL_AREA = 3500; // map units²: smaller states (Delhi, Goa, the north-east) get no number

/**
 * India by state, for the filter notebook: tap a state to filter by it. The
 * numbers are hackathons there under the other filters. A shortcut for pointer
 * and touch; the list under it is the same control for keyboards and screen readers.
 */
export function StateMap({ counts, selected, onToggle }: { counts: Map<string, number>; selected: string[]; onToggle: (state: string) => void }) {
  const [map, setMap] = useState<MiniMap | null>(loaded);
  useEffect(() => {
    if (map) return;
    let live = true;
    import("../assets/india-states.json").then((m) => {
      loaded = m.default as MiniMap;
      if (live) setMap(loaded);
    });
    return () => {
      live = false;
    };
  }, [map]);

  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const k = map && width ? width / map.width : 0;
  return (
    <div ref={ref} className="statemap" style={{ aspectRatio: map ? `${map.width} / ${map.height}` : "1000 / 1112" }} aria-hidden="true">
      {map && (
        <svg viewBox={`0 0 ${map.width} ${map.height}`}>
          {map.states.map((s) => {
            const n = counts.get(s.name) ?? 0;
            const on = selected.includes(s.name);
            return (
              <path
                key={s.name}
                d={s.d}
                className={`statemap__state${n ? " has-some" : ""}${on ? " is-on" : ""}`}
                onClick={n || on ? () => onToggle(s.name) : undefined}
              >
                <title>{`${s.name}: ${n ? n : "none"}`}</title>
              </path>
            );
          })}
          <path className="statemap__outline" d={map.outline} />
          {map.states
            .filter((s) => selected.includes(s.name))
            .map((s) => (
              <path key={s.name} className="statemap__picked" d={s.d} />
            ))}
          {k > 0 &&
            map.states
              .filter((s) => (counts.get(s.name) ?? 0) > 0 && s.area >= MIN_LABEL_AREA)
              .map((s) => (
                <text
                  key={s.name}
                  className={`statemap__n${selected.includes(s.name) ? " is-on" : ""}`}
                  x={s.at[0]}
                  y={s.at[1]}
                  fontSize={10 / k}
                  textAnchor="middle"
                  dominantBaseline="central"
                >
                  {counts.get(s.name)}
                </text>
              ))}
        </svg>
      )}
    </div>
  );
}
