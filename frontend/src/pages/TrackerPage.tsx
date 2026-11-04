import { ArrowUpRight, CalendarClock, ChevronDown, ClipboardCopy, Download, Link2, Plus, Share2, Trash2, Upload, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { OpenNoticeLink } from "../components/NoticeParts";
import { useToast } from "../components/Toast";
import { useCatalog, useNow } from "../lib/catalog";
import { countdown, fmtDate, fmtDay, fmtMonth, fmtRange, fmtTime, plural } from "../lib/format";
import { DAY, HOUR } from "../lib/lifecycle";
import { busyRanges, CHECKLIST, STATUS_LABEL, TRACK_STATUSES, tracker, useStore, type Tracked, type TrackStatus } from "../lib/tracker";
import type { Hackathon } from "../lib/types";

interface Row {
  t: Tracked;
  h?: Hackathon;
  id: string;
  title: string;
  url: string;
  sourceName: string;
  organizer?: string;
  mode?: string;
  start?: number;
  end?: number;
  regDeadline?: number;
  subDeadline?: number;
}

const ts = (v?: string) => (v ? Date.parse(v) : undefined);

function toRow(t: Tracked, h?: Hackathon): Row {
  const s = t.snapshot;
  return {
    t,
    h,
    id: h?.id ?? t.id,
    title: h?.title ?? s.title,
    url: h?.url ?? s.url,
    sourceName: h?.sourceName ?? s.sourceName,
    organizer: h?.organizer ?? s.organizer,
    mode: h?.mode ?? s.mode,
    start: h ? h.start : ts(s.starts_at),
    end: h ? h.end : ts(s.ends_at),
    regDeadline: h ? h.regDeadline : ts(s.registration_deadline),
    subDeadline: h ? h.subDeadline : ts(s.submission_deadline),
  };
}

interface DiaryEntry {
  at: number;
  row: Row;
  what: string;
  urgent: boolean;
}

/** The dates that matter for a tracked event, given how far along you are. */
function diaryFor(r: Row, now: number): DiaryEntry[] {
  const out: DiaryEntry[] = [];
  const st = r.t.status;
  if (st === "saved" && r.regDeadline && r.regDeadline > now) out.push({ at: r.regDeadline, row: r, what: "Register by", urgent: r.regDeadline - now < 3 * DAY });
  if ((st === "saved" || st === "applied") && r.start && r.start > now) out.push({ at: r.start, row: r, what: "Starts", urgent: false });
  const sub = r.subDeadline ?? r.end;
  if ((st === "applied" || st === "saved") && sub && sub > now) out.push({ at: sub, row: r, what: r.subDeadline ? "Submit by" : "Ends", urgent: sub - now < 2 * DAY });
  return out;
}

const ACTIVE: TrackStatus[] = ["saved", "applied", "submitted", "shortlisted"];
const isIntense = (r: Row) => !!r.start && !!r.end && r.end - r.start <= 5 * DAY;

function parsePrize(text?: string): number {
  if (!text) return 0;
  const m = text.replace(/,/g, "").match(/(\d+(?:\.\d+)?)\s*(k|l|lakh|lac|cr|crore|m)?/i);
  if (!m) return 0;
  const mult: Record<string, number> = { k: 1e3, l: 1e5, lakh: 1e5, lac: 1e5, cr: 1e7, crore: 1e7, m: 1e6 };
  return Number(m[1]) * (mult[(m[2] ?? "").toLowerCase()] ?? 1);
}

export function TrackerPage() {
  const { byId, state } = useCatalog();
  const store = useStore();
  const now = useNow();
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const fileRef = useRef<HTMLInputElement>(null);
  const [showDropped, setShowDropped] = useState(false);

  const rows = useMemo(
    () =>
      Object.values(store.items)
        .map((t) => toRow(t, byId.get(t.id)))
        .sort((a, b) => (a.start ?? Infinity) - (b.start ?? Infinity)),
    [store.items, byId],
  );
  const active = rows.filter((r) => ACTIVE.includes(r.t.status));

  const diary = useMemo(
    () =>
      active
        .flatMap((r) => diaryFor(r, now))
        .filter((e) => e.at - now <= 45 * DAY)
        .sort((a, b) => a.at - b.at),
    [active, now],
  );

  const clashes = useMemo(() => {
    const out: [Row, Row][] = [];
    const upcoming = active.filter((r) => r.start && r.end && r.end > now);
    for (let i = 0; i < upcoming.length; i++)
      for (let j = i + 1; j < upcoming.length; j++) {
        const a = upcoming[i];
        const b = upcoming[j];
        const overlap = a.start! < b.end! && b.start! < a.end!;
        const matters = (isIntense(a) && isIntense(b)) || (a.mode !== "online" && b.mode !== "online" && (isIntense(a) || isIntense(b)));
        if (overlap && matters) out.push([a, b]);
      }
    return out;
  }, [active, now]);

  const busy = useMemo(() => busyRanges(store), [store]);
  const busyClashes = useMemo(
    () =>
      active
        .filter((r) => r.start && (r.end ?? r.start) > now)
        .flatMap((r) => {
          const end = r.end && r.end - r.start! < 10 * DAY ? r.end : r.start! + DAY;
          const b = busy.find((x) => r.start! <= x.to && end >= x.from);
          return b ? [{ r, label: b.label }] : [];
        }),
    [active, busy, now],
  );

  // capacity: intense events and their hours, per month (from today onward)
  const months = useMemo(() => {
    const map = new Map<string, { ms: number; intense: number; hours: number; long: number }>();
    for (const r of active) {
      if (!r.start || !r.end || r.end < now) continue;
      const d = new Date(r.start);
      const key = `${d.getFullYear()}-${d.getMonth()}`;
      const m = map.get(key) ?? { ms: new Date(d.getFullYear(), d.getMonth(), 1).getTime(), intense: 0, hours: 0, long: 0 };
      if (isIntense(r)) {
        m.intense++;
        m.hours += Math.min((r.end - r.start) / HOUR, 72);
      } else m.long++;
      map.set(key, m);
    }
    return [...map.values()].sort((a, b) => a.ms - b.ms).slice(0, 4);
  }, [active, now]);

  const count = (s: TrackStatus[]) => rows.filter((r) => s.includes(r.t.status)).length;
  const finished = count(["won", "lost"]);
  const won = count(["won"]);
  const prizeTotal = rows.reduce((sum, r) => sum + (r.t.status === "won" ? parsePrize(r.t.prizeWon) : 0), 0);
  const prizeSymbol = rows.map((r) => (r.t.status === "won" ? r.t.prizeWon?.match(/[₹$€£]/)?.[0] : undefined)).find(Boolean) ?? "";

  const ids = rows.filter((r) => r.t.status !== "withdrawn").map((r) => r.id);
  const icsPath = `/api/calendar.ics?ids=${encodeURIComponent(ids.join(","))}`;
  const webcal = `${window.location.origin.replace(/^https?/, "webcal")}${icsPath}`;

  // a friend's shared list: /tracker?shared=a,b,c
  const sharedIds = (sp.get("shared") ?? "").split(",").filter(Boolean);
  const shared = sharedIds.map((id) => byId.get(id)).filter((h): h is Hackathon => !!h);

  const copy = async (text: string, msg: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast({ message: msg });
    } catch {
      window.prompt("Copy this", text);
    }
  };

  const exportFile = () => {
    const blob = new Blob([tracker.exportJSON()], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `hackmash-tabs-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const importFile = async (file: File) => {
    try {
      const n = tracker.importJSON(await file.text());
      toast({ message: n ? `Imported ${plural(n, "tab")}.` : "Nothing new in that file: you already have all of it." });
    } catch (e) {
      toast({ message: e instanceof Error ? e.message : "Couldn’t read that file." });
    }
  };

  const resumeLines = () => {
    const done = rows.filter((r) => ["submitted", "shortlisted", "won", "lost"].includes(r.t.status));
    const lines = done.map((r) => {
      const when = r.start ? new Date(r.start).toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "";
      const result = r.t.status === "won" ? (r.t.prizeWon ? `${r.t.prizeWon}, ` : "Winner, ") : r.t.status === "shortlisted" ? "Finalist, " : "";
      const link = r.t.projectUrl ? ` (${r.t.projectUrl})` : "";
      return `- ${result}${r.title}, ${r.sourceName}${when ? `, ${when}` : ""}${link}`;
    });
    return lines.join("\n");
  };

  const columns: { key: string; title: string; statuses: TrackStatus[] }[] = [
    { key: "saved", title: "Saved", statuses: ["saved"] },
    { key: "applied", title: "Applied", statuses: ["applied"] },
    { key: "submitted", title: "Submitted", statuses: ["submitted", "shortlisted"] },
    { key: "results", title: "Results", statuses: ["won", "lost"] },
  ];
  const dropped = rows.filter((r) => r.t.status === "withdrawn");

  return (
    <main id="main" className="page tracker">
      <div className="tracker__head">
        <div>
          <h1 className="page-title">My tabs</h1>
          <p className="page-lede">
            {rows.length === 0
              ? "Everything you save or apply to lands here, with its deadlines. It lives in this browser only."
              : `${plural(active.length, "hackathon")} in progress${diary.length ? `, ${plural(diary.filter((d) => d.at - now < 7 * DAY).length, "date")} in the next 7 days` : ""}. Stored only in this browser.`}
          </p>
        </div>
        <div className="tracker__tools">
          <button type="button" className="btn btn--sm" onClick={exportFile} disabled={rows.length === 0}>
            <Download size={15} aria-hidden="true" /> Export
          </button>
          <button type="button" className="btn btn--sm" onClick={() => fileRef.current?.click()}>
            <Upload size={15} aria-hidden="true" /> Import
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void importFile(f);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className="btn btn--sm"
            disabled={count(["submitted", "shortlisted", "won", "lost"]) === 0}
            onClick={() => copy(resumeLines(), "Résumé lines copied: paste them into your CV or LinkedIn.")}
            title="Copy the hackathons you submitted to, with results and project links"
          >
            <ClipboardCopy size={15} aria-hidden="true" /> Résumé lines
          </button>
          <button type="button" className="btn btn--sm" disabled={ids.length === 0} onClick={() => copy(`${window.location.origin}/tracker?shared=${ids.join(",")}`, "Share link copied. Teammates can add these to their own tabs.")}>
            <Share2 size={15} aria-hidden="true" /> Share list
          </button>
        </div>
      </div>

      {shared.length > 0 && (
        <section className="shared paper">
          <span className="pin pin--blue shared__pin" aria-hidden="true" />
          <h2 className="shared__title">Someone shared {plural(shared.length, "hackathon")} with you</h2>
          <ul className="shared__list">
            {shared.map((h) => (
              <li key={h.id}>
                <OpenNoticeLink id={h.id}>{h.title}</OpenNoticeLink>
                <span className="notice__muted"> · {h.sourceName} · {fmtRange(h.start, h.end, now)}</span>
                {store.items[h.id] ? (
                  <span className="hand shared__have">already in your tabs</span>
                ) : (
                  <button type="button" className="btn btn--sm" onClick={() => tracker.track(h, "saved")}>
                    Save
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="shared__foot">
            <button type="button" className="btn btn--sm btn--ink" onClick={() => shared.forEach((h) => !store.items[h.id] && tracker.track(h, "saved"))}>
              Save all
            </button>
            <button type="button" className="btn btn--sm btn--ghost" onClick={() => { sp.delete("shared"); setSp(sp, { replace: true }); }}>
              Dismiss
            </button>
          </div>
        </section>
      )}

      {rows.length === 0 ? (
        <div className="board-note paper tracker__empty">
          <span className="pin pin--blue board-note__pin" aria-hidden="true" />
          <p className="hand tracker__empty-note">Nothing pinned here yet.</p>
          <p>
            On the board, press <strong>Save</strong> on anything that looks good, or <strong>I applied</strong> once you have registered on the
            platform. Deadlines, clashes and your checklist show up here.
          </p>
          <Link className="btn btn--ink" to="/">
            Browse the board
          </Link>
        </div>
      ) : (
        <>
          <div className="tracker__overview">
            <section className="reportcard paper" aria-labelledby="rc-title">
              <h2 id="rc-title" className="reportcard__title">Report card</h2>
              <table className="reportcard__table">
                <tbody>
                  <tr>
                    <th scope="row">In progress</th>
                    <td>{active.length}</td>
                  </tr>
                  <tr>
                    <th scope="row">Applied to</th>
                    <td>{count(["applied", "submitted", "shortlisted", "won", "lost"])}</td>
                  </tr>
                  <tr>
                    <th scope="row">Submitted</th>
                    <td>{count(["submitted", "shortlisted", "won", "lost"])}</td>
                  </tr>
                  <tr>
                    <th scope="row">Won or placed</th>
                    <td>
                      {won}
                      {finished > 0 && <span className="notice__muted"> of {finished} finished</span>}
                    </td>
                  </tr>
                  {prizeTotal > 0 && (
                    <tr>
                      <th scope="row">Prize money noted</th>
                      <td>
                        {prizeSymbol}
                        {prizeTotal.toLocaleString(prizeSymbol === "₹" ? "en-IN" : "en-US")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              {months.length > 0 && (
                <div className="reportcard__months">
                  {months.map((m) => (
                    <p key={m.ms} className={m.intense >= 3 ? "is-heavy" : ""}>
                      <strong>{fmtMonth(m.ms)}:</strong> {m.intense ? `${plural(m.intense, "short event")}, about ${Math.round(m.hours)} h of hacking` : "no short events"}
                      {m.long ? `, plus ${plural(m.long, "long online one")}` : ""}
                      {m.intense >= 3 && <span className="reportcard__warn"> · that’s a lot of weekends; leave room for sleep and exams</span>}
                    </p>
                  ))}
                </div>
              )}
            </section>

            <section className="diary paper" aria-labelledby="diary-title">
              <h2 id="diary-title" className="diary__title">
                <CalendarClock size={18} aria-hidden="true" /> Coming up
              </h2>
              {busyClashes.map(({ r, label }) => (
                <p key={`busy-${r.id}`} className="diary__clash">
                  <span className="stamp">Busy</span>
                  <span>
                    <strong>{r.title}</strong> falls in your busy dates ({label}).
                  </span>
                </p>
              ))}
              {clashes.map(([a, b]) => (
                <p key={`${a.id}|${b.id}`} className="diary__clash">
                  <span className="stamp">Clash</span>
                  <span>
                    <strong>{a.title}</strong> and <strong>{b.title}</strong> overlap ({fmtRange(Math.max(a.start!, b.start!), Math.min(a.end!, b.end!), now)}).
                  </span>
                </p>
              ))}
              {diary.length === 0 ? (
                <p className="notice__muted">No deadlines in the next 45 days.</p>
              ) : (
                <ol className="diary__list">
                  {diary.slice(0, 12).map((e) => (
                    <li key={`${e.row.id}-${e.what}`} className={e.urgent ? "is-urgent" : ""}>
                      <span className="diary__date">
                        {fmtDay(e.at)}
                        <small>{fmtTime(e.at)}</small>
                      </span>
                      <span className="diary__what">
                        {e.what} <OpenNoticeLink id={e.row.id}>{e.row.title}</OpenNoticeLink>
                      </span>
                      <span className="diary__left">{countdown(e.at, now)}</span>
                    </li>
                  ))}
                </ol>
              )}
              <div className="diary__cal">
                <a className="btn btn--sm" href={webcal}>
                  <CalendarClock size={15} aria-hidden="true" /> Subscribe in your calendar
                </a>
                <a className="btn btn--sm" href={icsPath} download="hackmash.ics">
                  <Download size={15} aria-hidden="true" /> .ics
                </a>
                <button type="button" className="btn btn--sm btn--ghost" onClick={() => copy(`${window.location.origin}${icsPath}`, "Calendar feed URL copied. Paste it into Google Calendar → Other calendars → From URL.")}>
                  <Link2 size={15} aria-hidden="true" /> Copy feed URL
                </button>
              </div>
              <p className="diary__hint">
                Submit a few hours early: portals slow down at the cutoff. The calendar includes reminders two days and three hours before each
                registration and submission deadline. Re-subscribe after adding new tabs.
              </p>
            </section>
          </div>

          <BusyDates />

          <div className="kanban">
            {columns.map((col) => {
              const items = rows.filter((r) => col.statuses.includes(r.t.status));
              return (
                <section key={col.key} className="kanban__col" aria-labelledby={`col-${col.key}`}>
                  <h2 id={`col-${col.key}`} className="kanban__title">
                    {col.title} <span className="kanban__n">{items.length}</span>
                  </h2>
                  {items.length === 0 ? (
                    <p className="kanban__empty hand">
                      {col.key === "saved" ? "save notices from the board" : col.key === "applied" ? "tear “I applied” off a notice" : col.key === "submitted" ? "mark it submitted once it’s in" : "wins and lessons land here"}
                    </p>
                  ) : (
                    items.map((r) => <TabCard key={r.id} r={r} now={now} catalogReady={state === "ready"} />)
                  )}
                </section>
              );
            })}
          </div>

          {dropped.length > 0 && (
            <section className="dropped">
              <button type="button" className="btn btn--sm btn--ghost dropped__toggle" onClick={() => setShowDropped((v) => !v)} aria-expanded={showDropped}>
                <ChevronDown size={15} style={{ transform: showDropped ? "rotate(180deg)" : undefined }} aria-hidden="true" /> {plural(dropped.length, "dropped hackathon")}
              </button>
              {showDropped && (
                <div className="kanban kanban--dropped">
                  {dropped.map((r) => (
                    <TabCard key={r.id} r={r} now={now} catalogReady={state === "ready"} />
                  ))}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </main>
  );
}

function TabCard({ r, now, catalogReady }: { r: Row; now: number; catalogReady: boolean }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const t = r.t;
  const done = CHECKLIST.filter((c) => t.checklist?.[c.key]).length;
  const next = diaryFor(r, now)[0];
  const ended = (r.end ?? r.subDeadline ?? Infinity) < now;
  const gone = catalogReady && !r.h;

  return (
    <article className={`tabcard tabcard--${t.status}`}>
      <p className="tabcard__src">
        {r.sourceName}
        {r.organizer && <span> · {r.organizer}</span>}
      </p>
      <h3 className="tabcard__title">
        {gone ? (
          <a href={r.url} target="_blank" rel="noopener noreferrer">
            {r.title}
          </a>
        ) : (
          <OpenNoticeLink id={r.id}>{r.title}</OpenNoticeLink>
        )}
      </h3>
      <p className="tabcard__when">
        {fmtRange(r.start, r.end, now)}
        {ended && t.status !== "won" && t.status !== "lost" && t.status !== "withdrawn" && <span className="tabcard__ended"> · ended: how did it go?</span>}
      </p>
      {next && (
        <p className={`tabcard__next${next.urgent ? " is-urgent" : ""}`}>
          {next.what} {fmtDate(next.at, now)}, {fmtTime(next.at)} <span>({countdown(next.at, now)} left)</span>
        </p>
      )}

      <div className="tabcard__row">
        <label className="visually-hidden" htmlFor={`st-${r.id}`}>
          Status
        </label>
        <select id={`st-${r.id}`} className="field field--inline tabcard__status" value={t.status} onChange={(e) => tracker.setStatus(t.id, e.target.value as TrackStatus)}>
          {TRACK_STATUSES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <button type="button" className="tabcard__check" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {done}/{CHECKLIST.length} done <ChevronDown size={14} style={{ transform: open ? "rotate(180deg)" : undefined }} aria-hidden="true" />
        </button>
      </div>

      {t.notes && !open && <p className="tabcard__notes hand">{t.notes}</p>}

      {open && (
        <div className="tabcard__more">
          <ul className="tabcard__checklist">
            {CHECKLIST.map((c) => (
              <li key={c.key}>
                <label>
                  <input type="checkbox" checked={!!t.checklist?.[c.key]} onChange={(e) => tracker.patch(t.id, { checklist: { ...(t.checklist ?? {}), [c.key]: e.target.checked } })} />
                  <span>{c.label}</span>
                </label>
              </li>
            ))}
          </ul>
          <label className="tabcard__field">
            <span>Notes</span>
            <textarea className="field hand-field" rows={3} defaultValue={t.notes ?? ""} placeholder="Idea, track, who does what…" onBlur={(e) => tracker.patch(t.id, { notes: e.target.value })} />
          </label>
          <label className="tabcard__field">
            <span>Team</span>
            <input className="field" defaultValue={t.team ?? ""} placeholder="Names or handles" onBlur={(e) => tracker.patch(t.id, { team: e.target.value })} />
          </label>
          <label className="tabcard__field">
            <span>Project link</span>
            <input className="field" type="url" defaultValue={t.projectUrl ?? ""} placeholder="GitHub repo, demo, Devpost page" onBlur={(e) => tracker.patch(t.id, { projectUrl: e.target.value })} />
          </label>
          {(t.status === "won" || t.status === "lost") && (
            <label className="tabcard__field">
              <span>{t.status === "won" ? "What you won" : "Feedback / lessons"}</span>
              <input className="field" defaultValue={t.prizeWon ?? ""} placeholder={t.status === "won" ? "₹25,000, 2nd place" : "What to do differently"} onBlur={(e) => tracker.patch(t.id, { prizeWon: e.target.value })} />
            </label>
          )}
          <div className="tabcard__actions">
            {t.projectUrl && (
              <a className="btn btn--sm" href={t.projectUrl} target="_blank" rel="noopener noreferrer">
                Project <ArrowUpRight size={13} aria-hidden="true" />
              </a>
            )}
            <a className="btn btn--sm" href={r.url} target="_blank" rel="noopener noreferrer">
              {r.sourceName} <ArrowUpRight size={13} aria-hidden="true" />
            </a>
            <button
              type="button"
              className="btn btn--sm btn--ghost tabcard__remove"
              onClick={() => {
                const snapshot = { ...t };
                tracker.untrack(t.id);
                toast({
                  message: `Removed “${r.title}”.`,
                  action: {
                    label: "Undo",
                    run: () => tracker.restore(snapshot),
                  },
                });
              }}
            >
              <Trash2 size={14} aria-hidden="true" /> Remove
            </button>
          </div>
          <p className="tabcard__meta">
            {STATUS_LABEL[t.status]} · updated {fmtDate(t.updatedAt, now)}
          </p>
        </div>
      )}
    </article>
  );
}

/** Exam weeks, trips, anything: the board can hide events that clash with them. */
function BusyDates() {
  const store = useStore();
  const [label, setLabel] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  return (
    <section className="busy paper" aria-labelledby="busy-title">
      <div className="busy__head">
        <h2 id="busy-title" className="busy__title">Busy dates</h2>
        <p className="busy__lede">Exams, trips, fests. Events that clash get flagged here and on the board, and the board can hide them.</p>
      </div>
      {store.busy.length > 0 && (
        <ul className="busy__list">
          {store.busy.map((b) => (
            <li key={b.id}>
              <span className="hand busy__label">{b.label}</span>
              <span className="busy__dates">
                {fmtDate(Date.parse(`${b.from}T12:00:00`))}
                {b.to !== b.from && ` – ${fmtDate(Date.parse(`${b.to}T12:00:00`))}`}
              </span>
              <button type="button" className="icon-btn" onClick={() => tracker.removeBusy(b.id)} aria-label={`Remove ${b.label}`}>
                <X size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="busy__form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!from) return;
          tracker.addBusy(label.trim() || "Busy", from, to && to >= from ? to : from);
          setLabel("");
          setFrom("");
          setTo("");
        }}
      >
        <label>
          <span>What</span>
          <input className="field" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="End-sem exams" />
        </label>
        <label>
          <span>From</span>
          <input className="field" type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
        </label>
        <label>
          <span>To</span>
          <input className="field" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button type="submit" className="btn btn--sm btn--ink" disabled={!from}>
          <Plus size={15} aria-hidden="true" /> Add
        </button>
      </form>
    </section>
  );
}
