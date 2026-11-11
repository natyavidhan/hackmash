import { ArrowUpRight, EyeOff, Users } from "lucide-react";
import { memo } from "react";
import { fmtDuration, fmtRange, placeLabel, prizeMagnitude, prizeParts, teamLabel } from "../lib/format";
import { lifecycle } from "../lib/lifecycle";
import { tracker, type Tracked } from "../lib/tracker";
import type { Hackathon, Taxonomy } from "../lib/types";
import { DeadlineStamp, OpenNoticeLink, STOCK, TimeLeft, TrackTabs, pinFor } from "./NoticeParts";
import { useToast } from "./Toast";

interface Props {
  h: Hackathon;
  now: number;
  currency: string;
  fx?: Record<string, number>;
  taxonomy: Taxonomy;
  tracked?: Tracked;
  isNew: boolean;
  dismissed: boolean;
  busyClash?: string;
}

export const NoticeCard = memo(function NoticeCard({ h, now, currency, fx, taxonomy, tracked, isNew, dismissed, busyClash }: Props) {
  const toast = useToast();
  const stock = STOCK[h.kind ?? "hackathon"] ?? "white";
  const prize = prizeParts(h, currency, fx);
  const magnitude = prizeMagnitude(prize.usd);
  const team = teamLabel(h);
  const duration = fmtDuration(h.duration_hours);
  const themes = (h.themes ?? []).slice(0, 3).map((t) => taxonomy.themes[t] ?? t);
  const extra = (h.also_on ?? []).length;
  const titleId = `n-${h.id}`;

  const flags: { label: string; tone?: "warn" | "good" }[] = [];
  // only search turns these up: under way, but registration has closed
  if (!lifecycle(h, now).regOpen) flags.push({ label: "Registration closed", tone: "warn" });
  if (busyClash) flags.push({ label: `Clashes with ${busyClash}`, tone: "warn" });
  if (h.deadline_extended) flags.push({ label: "Deadline extended", tone: "good" });
  if (h.registration_fee) flags.push({ label: "Paid entry", tone: "warn" });
  if (h.hiring) flags.push({ label: "Hiring" });
  if (h.beginner_friendly) flags.push({ label: "Beginner-friendly", tone: "good" });
  if (h.travel_reimbursement) flags.push({ label: "Travel reimbursed", tone: "good" });
  if (h.audience?.includes("high_school")) flags.push({ label: "High school" });
  else if (h.audience?.includes("women")) flags.push({ label: "Women & non-binary" });
  else if (h.audience?.includes("students")) flags.push({ label: "Students" });
  if (h.kind && h.kind !== "hackathon") flags.unshift({ label: taxonomy.kinds[h.kind] ?? h.kind });

  return (
    <article className={`notice notice--${stock}`} aria-labelledby={titleId}>
      <span className={`pin pin--${pinFor(h, now, tracked)} notice__pin`} aria-hidden="true" />
      {isNew && (
        <span className="sticker notice__new" aria-label="New since your last visit">
          New
        </span>
      )}
      <header className="notice__head">
        <span className="notice__source">
          {h.sourceName}
          {extra > 0 && <span className="notice__also"> +{extra}</span>}
        </span>
        {h.organizer && <span className="notice__org">{h.organizer}</span>}
      </header>

      <h3 className="notice__title" id={titleId}>
        <OpenNoticeLink id={h.id} className="notice__open">
          {h.title}
        </OpenNoticeLink>
      </h3>

      <div className="notice__deadline">
        <DeadlineStamp h={h} now={now} />
        <TimeLeft h={h} now={now} />
      </div>

      <dl className="notice__facts">
        <div>
          <dt>When</dt>
          <dd>
            {fmtRange(h.start, h.end, now)}
            {duration && <span className="notice__muted"> · {duration}</span>}
          </dd>
        </div>
        <div>
          <dt>Where</dt>
          <dd>{placeLabel(h)}</dd>
        </div>
        <div>
          <dt>Prize</dt>
          <dd>
            {prize.main ? (
              <>
                <span className="notice__prize">{prize.main}</span>
                {prize.alt && <span className="notice__muted"> {prize.alt}</span>}
                {magnitude > 0 && (
                  <span className="ramp" aria-hidden="true" title="Prize pool on a five-step scale">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <i key={i} className={i <= magnitude ? "on" : ""} />
                    ))}
                  </span>
                )}
              </>
            ) : (
              <span className="notice__muted">Not published</span>
            )}
          </dd>
        </div>
        {(team || h.participants) && (
          <div>
            <dt>Team</dt>
            <dd>
              {team ?? <span className="notice__muted">Any size</span>}
              {h.participants ? (
                <span className="notice__muted notice__regs">
                  <Users size={12} aria-hidden="true" /> {h.participants.toLocaleString("en-IN")}
                </span>
              ) : null}
            </dd>
          </div>
        )}
      </dl>

      {(themes.length > 0 || flags.length > 0) && (
        <div className="notice__labels">
          {flags.map((f) => (
            <span key={f.label} className={`label${f.tone ? ` label--${f.tone}` : ""}`}>
              {f.label}
            </span>
          ))}
          {themes.map((t) => (
            <span key={t} className="label label--theme">
              {t}
            </span>
          ))}
        </div>
      )}

      <div className="notice__spacer" />
      <footer className="notice__tabs">
        <a className="tab tab--apply" href={h.url} target="_blank" rel="noopener noreferrer">
          <span>Open on {h.sourceName}</span>
          <ArrowUpRight size={15} aria-hidden="true" />
        </a>
        <TrackTabs h={h} tracked={tracked} compact />
      </footer>

      <button
        type="button"
        className="notice__hide"
        onClick={() => {
          if (dismissed) {
            tracker.undismiss(h.id);
          } else {
            tracker.dismiss(h.id);
            toast({ message: "Notice hidden from your board.", action: { label: "Undo", run: () => tracker.undismiss(h.id) } });
          }
        }}
        aria-label={dismissed ? `Put ${h.title} back on the board` : `Hide ${h.title} from my board`}
        title={dismissed ? "Put back on the board" : "Not interested: hide it"}
      >
        <EyeOff size={14} aria-hidden="true" />
      </button>
    </article>
  );
});
