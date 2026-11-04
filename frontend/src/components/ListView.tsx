import { ArrowUpRight } from "lucide-react";
import { fmtRange, placeLabel, prizeParts } from "../lib/format";
import type { Tracked } from "../lib/tracker";
import type { Hackathon, Taxonomy } from "../lib/types";
import { DeadlineStamp, OpenNoticeLink, TimeLeft, TrackTabs } from "./NoticeParts";

interface Props {
  items: Hackathon[];
  now: number;
  currency: string;
  fx?: Record<string, number>;
  tracked: Record<string, Tracked>;
  taxonomy: Taxonomy;
}

/** The board's register book: one ruled line per hackathon, for fast scanning. */
export function ListView({ items, now, currency, fx, tracked, taxonomy }: Props) {
  return (
    <div className="register paper">
      <table className="register__table">
        <thead>
          <tr>
            <th scope="col">Next date</th>
            <th scope="col">Hackathon</th>
            <th scope="col">When</th>
            <th scope="col">Where</th>
            <th scope="col">Prize</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((h) => {
            const prize = prizeParts(h, currency, fx);
            return (
              <tr key={h.id} className="register__row">
                <td className="register__date">
                  <DeadlineStamp h={h} now={now} />
                  <TimeLeft h={h} now={now} />
                </td>
                <td className="register__title">
                  <OpenNoticeLink id={h.id}>{h.title}</OpenNoticeLink>
                  <span className="register__sub">
                    {h.sourceName}
                    {(h.also_on ?? []).length > 0 && ` +${h.also_on!.length}`}
                    {h.organizer && ` · ${h.organizer}`}
                    {h.kind && h.kind !== "hackathon" && ` · ${taxonomy.kinds[h.kind] ?? h.kind}`}
                  </span>
                </td>
                <td className="register__when">{fmtRange(h.start, h.end, now)}</td>
                <td className="register__where">{placeLabel(h)}</td>
                <td className="register__prize">
                  {prize.main ?? <span className="notice__muted">Not published</span>}
                  {prize.alt && <span className="register__alt">{prize.alt}</span>}
                </td>
                <td className="register__actions">
                  <a className="tab tab--apply-sm" href={h.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${h.title} on ${h.sourceName}`}>
                    <ArrowUpRight size={16} aria-hidden="true" />
                  </a>
                  <TrackTabs h={h} tracked={tracked[h.id]} compact />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
