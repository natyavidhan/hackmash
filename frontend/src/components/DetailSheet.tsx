import { ArrowUpRight, CalendarPlus, Check, Copy, Download, Flag, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useCatalog, useNow } from "../lib/catalog";
import {
  fmtDateTime,
  fmtDuration,
  fmtRange,
  placeLabel,
  prizeParts,
  relativeAgo,
  teamLabel,
  timeZoneLabel,
  tzOffset,
} from "../lib/format";
import { lifecycle } from "../lib/lifecycle";
import { busyRanges, currencyPref, STATUS_LABEL, TRACK_STATUSES, tracker, useStore, type TrackStatus } from "../lib/tracker";
import type { Hackathon } from "../lib/types";
import { DeadlineStamp, STOCK, TimeLeft } from "./NoticeParts";
import { useToast } from "./Toast";

const gcalDate = (ms: number) => new Date(ms).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

function googleCalendarUrl(h: Hackathon): string | undefined {
  const start = h.start ?? h.regDeadline ?? h.subDeadline;
  if (!start) return undefined;
  const end = h.end && h.end > start ? h.end : start + 3_600_000;
  const p = new URLSearchParams({
    action: "TEMPLATE",
    text: h.title,
    dates: `${gcalDate(start)}/${gcalDate(end)}`,
    details: `${h.tagline ?? ""}\n\nListed on ${h.sourceName}: ${h.url}\n(via Hackmash)`.trim(),
    location: h.mode === "online" ? "Online" : (h.location ?? ""),
  });
  return `https://calendar.google.com/calendar/render?${p}`;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="sheet__fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function DetailSheet() {
  const location = useLocation();
  const navigate = useNavigate();
  const { byId, taxonomy, sources, catalog, state } = useCatalog();
  const store = useStore();
  const now = useNow();
  const toast = useToast();
  const ref = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState(false);

  const id = new URLSearchParams(location.search).get("h");
  const h = id ? byId.get(id) : undefined;
  const tracked = id ? (store.items[id] ?? (h ? store.items[h.id] : undefined)) : undefined;
  const open = !!id;

  const close = () => {
    const sp = new URLSearchParams(location.search);
    sp.delete("h");
    const search = sp.toString();
    // came from the board: step back so the browser's back button stays sane
    if ((location.state as { fromBoard?: boolean } | null)?.fromBoard) navigate(-1);
    else navigate({ pathname: location.pathname, search: search ? `?${search}` : "" }, { replace: true });
  };

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  // keep the tracker's snapshot fresh when the platform updates dates or prizes
  useEffect(() => {
    if (h && store.items[h.id]) tracker.refreshSnapshot(h);
  }, [h, store.items]);

  useEffect(() => setCopied(false), [id]);

  const currency = currencyPref(store);

  let body: React.ReactNode = null;
  if (open && !h) {
    body =
      state === "loading" ? (
        <p className="sheet__empty">Finding that notice…</p>
      ) : (
        <div className="sheet__empty">
          <h2 className="sheet__title">This notice has come down</h2>
          <p>
            It ended more than 30 days ago or the platform removed it.
            {tracked && " Your notes on it are still in My tabs."}
          </p>
          {tracked && (
            <a className="btn" href={tracked.snapshot.url} target="_blank" rel="noopener noreferrer">
              Open the original page <ArrowUpRight size={15} />
            </a>
          )}
        </div>
      );
  } else if (h) {
    const { status, regOpen } = lifecycle(h, now);
    const prize = prizeParts(h, currency, catalog?.fx);
    const team = teamLabel(h);
    const duration = fmtDuration(h.duration_hours);
    const gcal = googleCalendarUrl(h);
    const src = sources[h.source];
    const shareUrl = `${window.location.origin}/?h=${encodeURIComponent(h.id)}`;
    const warnings: string[] = [];
    if (h.registration_fee) warnings.push("This event charges an entry fee. Check what it covers before paying.");
    if (h.invite_only) warnings.push("Invite-only: you need an invitation from the organisers to take part.");
    if (h.delisted) warnings.push(`${h.sourceName} no longer lists this event, so registration has probably closed.`);
    if (!prize.main && status !== "ended") warnings.push("No prize details are published yet.");
    const clash = h.start
      ? busyRanges(store).find((b) => h.start! <= b.to && (h.end && h.end - h.start! < 10 * 86_400_000 ? h.end : h.start! + 86_400_000) >= b.from)
      : undefined;
    if (clash) warnings.unshift(`This overlaps your busy dates: ${clash.label}.`);
    const ext = h.deadline_extended;
    const extNote = (field: string) =>
      ext && ext.field === field ? <span className="sheet__sub sheet__ext">Extended from {fmtDateTime(Date.parse(ext.old), now)}</span> : null;
    const inINR = currency === "INR" || h.prize_currency === "INR";
    const at = h.start ?? now;
    const eventOffset = h.timezone ? tzOffset(h.timezone, at) : undefined;
    const tzNote = eventOffset !== undefined && eventOffset !== -new Date(at).getTimezoneOffset() ? ` (local time at the event: ${h.timezone!.replace(/_/g, " ")})` : "";

    const setStatus = (s: TrackStatus | "") => {
      if (!s) {
        const prev = tracked?.status;
        tracker.untrack(h.id);
        if (prev) toast({ message: "Removed from My tabs.", action: { label: "Undo", run: () => tracker.track(h, prev) } });
      } else if (tracked) tracker.setStatus(h.id, s);
      else tracker.track(h, s);
    };

    body = (
      <article className="sheet__notice">
        <header className="sheet__head">
          {h.logo_url && <img className="sheet__logo" src={h.logo_url} alt="" width={52} height={52} loading="lazy" referrerPolicy="no-referrer" />}
          <div>
            <p className="sheet__letterhead">
              {h.sourceName}
              {h.organizer && <span> · {h.organizer}</span>}
            </p>
            <h2 className="sheet__title" id="sheet-title">
              {h.title}
            </h2>
            {h.tagline && <p className="sheet__tagline">{h.tagline}</p>}
          </div>
        </header>

        <div className="sheet__stamps">
          <DeadlineStamp h={h} now={now} size="lg" />
          <TimeLeft h={h} now={now} />
          {status === "live" && regOpen && <span className="stamp stamp--live stamp--lg">Still open to join</span>}
        </div>

        <div className="sheet__cta">
          <a className="btn btn--ink sheet__apply" href={h.url} target="_blank" rel="noopener noreferrer">
            {regOpen ? "Register" : "Open"} on {h.sourceName} <ArrowUpRight size={16} aria-hidden="true" />
          </a>
          {(h.also_on ?? []).map((l) => (
            <a key={l.id} className="btn" href={l.url} target="_blank" rel="noopener noreferrer">
              Also on {sources[l.source]?.name ?? l.source} <ArrowUpRight size={14} aria-hidden="true" />
            </a>
          ))}
        </div>

        {warnings.length > 0 && (
          <ul className="sheet__warnings">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}

        <dl className="sheet__facts">
          <Fact label="When">
            {fmtRange(h.start, h.end, now)}
            {duration && ` · ${duration}`}
            {h.start && (
              <span className="sheet__sub">
                {fmtDateTime(h.start, now)}
                {h.end ? ` → ${fmtDateTime(h.end, now)}` : ""} {timeZoneLabel()}
                {tzNote}
              </span>
            )}
          </Fact>
          {(h.regOpens || h.regDeadline) && (
            <Fact label="Registration">
              {h.regOpens && <span className="sheet__line">Opens {fmtDateTime(h.regOpens, now)}</span>}
              {h.regDeadline && <span className="sheet__line">Closes {fmtDateTime(h.regDeadline, now)}</span>}
              {extNote("registration_deadline")}
            </Fact>
          )}
          {h.subDeadline && (!h.end || Math.abs(h.subDeadline - h.end) > 3_600_000 || !h.regDeadline) && (
            <Fact label="Submit by">
              {fmtDateTime(h.subDeadline, now)}
              {extNote("submission_deadline")}
            </Fact>
          )}
          <Fact label="Where">
            {placeLabel(h)}
            {h.mode !== "online" && h.location && h.location !== placeLabel(h) && <span className="sheet__sub">{h.location}</span>}
          </Fact>
          <Fact label="Prizes">
            {prize.main ?? "Not published"}
            {prize.alt && <span className="sheet__sub">{prize.alt} at today’s rate</span>}
            {h.non_cash_prizes && prize.main && prize.main !== "Non-cash prizes" && <span className="sheet__sub">Plus non-cash prizes</span>}
            {inINR && h.prize_amount ? <span className="sheet__sub">In India, cash prizes over ₹10,000 usually have 30% TDS deducted.</span> : null}
          </Fact>
          <Fact label="Team">{team ?? "No limit published"}</Fact>
          {(h.audience?.length || h.eligibility?.length) && (
            <Fact label="Who can join">
              {(h.audience ?? []).map((a) => taxonomy.audiences[a] ?? a).join(", ")}
              {(h.eligibility ?? []).length > 0 && <span className="sheet__sub">{h.eligibility!.join(" · ")}</span>}
            </Fact>
          )}
          <Fact label="Entry">{h.registration_fee === true ? "Paid" : h.registration_fee === false ? "Free" : "Not stated"}</Fact>
          <Fact label="Format">{taxonomy.kinds[h.kind ?? "hackathon"] ?? h.kind}</Fact>
          {h.participants ? <Fact label="Registered">{h.participants.toLocaleString("en-IN")} people so far</Fact> : null}
          {h.beginner_friendly && <Fact label="Level">Beginner-friendly</Fact>}
          {h.travel_reimbursement && <Fact label="Travel">Reimbursement offered</Fact>}
          {h.hiring && <Fact label="Careers">Mentions jobs, internships or pre-placement interviews</Fact>}
        </dl>

        {((h.themes ?? []).length > 0 || (h.tags ?? []).length > 0) && (
          <div className="notice__labels sheet__labels">
            {(h.themes ?? []).map((t) => (
              <span key={t} className="label">
                {taxonomy.themes[t] ?? t}
              </span>
            ))}
            {(h.tags ?? [])
              .filter((t) => !(h.themes ?? []).some((th) => (taxonomy.themes[th] ?? "").toLowerCase() === t.toLowerCase()))
              .slice(0, 12)
              .map((t) => (
                <span key={t} className="label label--theme">
                  {t}
                </span>
              ))}
          </div>
        )}

        {h.description && (
          <section className="sheet__desc">
            <h3>About</h3>
            {h.description.split(/\n{2,}/).map((para, i) => (
              <p key={i}>{para}</p>
            ))}
            <a className="sheet__more" href={h.url} target="_blank" rel="noopener noreferrer">
              Full details, rules and judging criteria on {h.sourceName} <ArrowUpRight size={13} aria-hidden="true" />
            </a>
          </section>
        )}

        {h.image_url && (
          <figure className="sheet__photo">
            <img src={h.image_url} alt={`${h.title} banner`} loading="lazy" referrerPolicy="no-referrer" />
          </figure>
        )}

        <section className="sheet__track" aria-labelledby="track-title">
          <h3 id="track-title" className="hand">your tab</h3>
          <div className="sheet__statuses" role="radiogroup" aria-label="Where you are with this hackathon">
            <button type="button" role="radio" aria-checked={!tracked} className={!tracked ? "is-on" : ""} onClick={() => setStatus("")}>
              Not tracking
            </button>
            {TRACK_STATUSES.map((s) => (
              <button
                key={s.key}
                type="button"
                role="radio"
                aria-checked={tracked?.status === s.key}
                className={tracked?.status === s.key ? "is-on" : ""}
                onClick={() => setStatus(s.key)}
                title={s.hint}
              >
                {tracked?.status === s.key && <Check size={13} aria-hidden="true" />} {s.label}
              </button>
            ))}
          </div>
          {tracked ? (
            <label className="sheet__notes">
              <span>Notes for yourself</span>
              <textarea
                className="field hand-field"
                rows={3}
                placeholder="Team, idea, which track, what to submit…"
                defaultValue={tracked.notes ?? ""}
                key={`${h.id}-notes`}
                onBlur={(e) => tracker.patch(h.id, { notes: e.target.value })}
              />
            </label>
          ) : (
            <p className="sheet__hint">Pick a status to keep this in My tabs, with deadlines, notes and a checklist. Stored only in this browser.</p>
          )}
          {tracked && (
            <p className="sheet__hint">
              In My tabs as <strong>{STATUS_LABEL[tracked.status]}</strong> since {relativeAgo(tracked.addedAt, now)}.
            </p>
          )}
        </section>

        <section className="sheet__tools" aria-label="Calendar and sharing">
          {gcal && (
            <a className="btn btn--sm" href={gcal} target="_blank" rel="noopener noreferrer">
              <CalendarPlus size={15} aria-hidden="true" /> Google Calendar
            </a>
          )}
          <a className="btn btn--sm" href={`/api/hackathons/${encodeURIComponent(h.id)}/calendar.ics`} download>
            <Download size={15} aria-hidden="true" /> .ics with reminders
          </a>
          <button
            type="button"
            className="btn btn--sm"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(shareUrl);
                setCopied(true);
              } catch {
                window.prompt("Copy this link", shareUrl);
              }
            }}
          >
            {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />} {copied ? "Link copied" : "Copy link"}
          </button>
        </section>

        <footer className="sheet__provenance">
          Listed on <a href={src?.homepage ?? h.url}>{h.sourceName}</a>
          {h.first_seen_at && <> · first pinned {relativeAgo(Date.parse(h.first_seen_at), now)}</>}
          {h.last_seen_at && <> · checked {relativeAgo(Date.parse(h.last_seen_at), now)}</>}
          {" · "}
          <a
            href={`https://github.com/natyavidhan/hackmash/issues/new?title=${encodeURIComponent(`Listing problem: ${h.title}`)}&body=${encodeURIComponent(`${shareUrl}\n\nWhat is wrong?`)}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Flag size={12} aria-hidden="true" /> Report a problem
          </a>
        </footer>
      </article>
    );
  }

  const stock = h ? STOCK[h.kind ?? "hackathon"] : "white";

  // The dialog is the overlay that centres the card; the card holds the pin and
  // the close button and never scrolls, so both stay put while its body scrolls.
  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby="sheet-title"
      onClose={() => {
        if (new URLSearchParams(window.location.search).get("h")) close();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className={`sheet__card sheet__card--${stock}`}>
        {h && <span className="pin pin--red sheet__pin" aria-hidden="true" />}
        <button type="button" className="icon-btn sheet__close" onClick={close} aria-label="Close notice">
          <X size={22} />
        </button>
        <div className="sheet__scroll paper-scroll">{body}</div>
      </div>
    </dialog>
  );
}
