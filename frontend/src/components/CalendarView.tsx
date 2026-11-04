import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { fmtDay, fmtMonth, fmtTime } from "../lib/format";
import { lifecycle } from "../lib/lifecycle";
import type { Hackathon } from "../lib/types";
import { OpenNoticeLink, STOCK } from "./NoticeParts";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const dayKey = (ms: number) => {
  const d = new Date(ms);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
};

interface DayBucket {
  starts: Hackathon[];
  closes: Hackathon[];
}

/** A wall planner: what starts on each day, and which registrations close. */
export function CalendarView({ items, now }: { items: Hackathon[]; now: number }) {
  const [cursor, setCursor] = useState(() => {
    const d = new Date(now);
    return new Date(d.getFullYear(), d.getMonth(), 1).getTime();
  });
  const [selected, setSelected] = useState<string | null>(dayKey(now));

  const buckets = useMemo(() => {
    const map = new Map<string, DayBucket>();
    const get = (k: string) => {
      let b = map.get(k);
      if (!b) map.set(k, (b = { starts: [], closes: [] }));
      return b;
    };
    for (const h of items) {
      if (h.start) get(dayKey(h.start)).starts.push(h);
      const close = h.regDeadline ?? (h.mode !== "in_person" ? h.subDeadline : undefined);
      if (close && lifecycle(h, now).status !== "ended") get(dayKey(close)).closes.push(h);
    }
    return map;
  }, [items, now]);

  const cells = useMemo(() => {
    const first = new Date(cursor);
    const offset = (first.getDay() + 6) % 7; // Monday-first
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
    return Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  }, [cursor]);

  const month = new Date(cursor).getMonth();
  const todayKey = dayKey(now);
  const sel = selected ? buckets.get(selected) : undefined;
  const selDate = selected ? cells.find((c) => dayKey(c.getTime()) === selected) : undefined;

  const shift = (n: number) => {
    const d = new Date(cursor);
    setCursor(new Date(d.getFullYear(), d.getMonth() + n, 1).getTime());
    setSelected(null);
  };

  return (
    <div className="planner">
      <div className="planner__bar">
        <button type="button" className="icon-btn" onClick={() => shift(-1)} aria-label="Previous month">
          <ChevronLeft size={18} />
        </button>
        <h2 className="planner__month">{fmtMonth(cursor)}</h2>
        <button type="button" className="icon-btn" onClick={() => shift(1)} aria-label="Next month">
          <ChevronRight size={18} />
        </button>
        <p className="planner__legend">
          <span className="planner__swatch" /> starts <span className="planner__swatch planner__swatch--close" /> registration closes
        </p>
      </div>
      <div className="planner__grid paper" role="grid" aria-label={`Hackathons in ${fmtMonth(cursor)}`}>
        {WEEKDAYS.map((d) => (
          <div key={d} className="planner__dow" role="columnheader">
            {d}
          </div>
        ))}
        {cells.map((c) => {
          const k = dayKey(c.getTime());
          const b = buckets.get(k);
          const out = c.getMonth() !== month;
          const count = (b?.starts.length ?? 0) + (b?.closes.length ?? 0);
          return (
            <button
              type="button"
              role="gridcell"
              key={k}
              className={`planner__day${out ? " is-out" : ""}${k === todayKey ? " is-today" : ""}${selected === k ? " is-selected" : ""}`}
              onClick={() => setSelected(k)}
              aria-label={`${fmtDay(c.getTime())}: ${b?.starts.length ?? 0} starting, ${b?.closes.length ?? 0} closing`}
              disabled={count === 0 && out}
            >
              <span className="planner__num">{c.getDate()}</span>
              {b?.starts.slice(0, 3).map((h) => (
                <span key={h.id} className={`planner__slip planner__slip--${STOCK[h.kind ?? "hackathon"]}`}>
                  {h.title}
                </span>
              ))}
              {b && b.starts.length > 3 && <span className="planner__more">+{b.starts.length - 3} more</span>}
              {b && b.closes.length > 0 && <span className="planner__close">{b.closes.length} closing</span>}
            </button>
          );
        })}
      </div>

      {selected && selDate && (
        <div className="planner__detail paper">
          <h3 className="planner__detail-title">{fmtDay(selDate.getTime())}</h3>
          {!sel || (sel.starts.length === 0 && sel.closes.length === 0) ? (
            <p className="notice__muted">Nothing starts or closes on this day with your filters.</p>
          ) : (
            <div className="planner__cols">
              {sel.starts.length > 0 && (
                <section>
                  <h4>Starting</h4>
                  <ul>
                    {sel.starts.map((h) => (
                      <li key={h.id}>
                        <OpenNoticeLink id={h.id}>{h.title}</OpenNoticeLink>
                        <span className="notice__muted"> · {h.sourceName}{h.start ? ` · ${fmtTime(h.start)}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {sel.closes.length > 0 && (
                <section>
                  <h4 className="planner__closing-title">Registration closes</h4>
                  <ul>
                    {sel.closes.map((h) => (
                      <li key={h.id}>
                        <OpenNoticeLink id={h.id}>{h.title}</OpenNoticeLink>
                        <span className="notice__muted"> · {h.sourceName}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
