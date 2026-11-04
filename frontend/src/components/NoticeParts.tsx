import { Bookmark, BookmarkCheck, Check, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { DAY, lifecycle, nextDeadline } from "../lib/lifecycle";
import { countdown, fmtDate } from "../lib/format";
import { STATUS_LABEL, tracker, type Tracked } from "../lib/tracker";
import type { Hackathon } from "../lib/types";
import { useToast } from "./Toast";

export const STOCK: Record<string, string> = {
  hackathon: "white",
  ideathon: "yellow",
  coding_contest: "blue",
  data_science: "green",
  other: "pink",
};

export function pinFor(h: Hackathon, now: number, tracked?: Tracked): "blue" | "green" | "red" | "brass" {
  if (tracked && tracked.status !== "withdrawn") return "blue";
  const { status } = lifecycle(h, now);
  if (status === "live") return "green";
  const nd = nextDeadline(h, now);
  if (nd && nd.kind !== "start" && nd.at - now < 3 * DAY) return "red";
  return "brass";
}

/** The red rubber stamp: the one date that matters most right now. */
export function DeadlineStamp({ h, now, size = "md" }: { h: Hackathon; now: number; size?: "md" | "lg" }) {
  const { status, regOpen } = lifecycle(h, now);
  const nd = nextDeadline(h, now);
  const cls = `stamp stamp--${size}`;
  if (status === "ended") {
    const end = h.end ?? h.subDeadline;
    if (end && end > now && h.subDeadline) return <span className={`${cls} stamp--quiet`}>Closed · {fmtDate(h.subDeadline, now)}</span>;
    return <span className={`${cls} stamp--quiet`}>Ended{end ? ` · ${fmtDate(end, now)}` : ""}</span>;
  }
  if (h.regOpens && h.regOpens > now && !regOpen) {
    return (
      <span className={`${cls} stamp--pen`}>
        Reg. opens · {fmtDate(h.regOpens, now)}
      </span>
    );
  }
  if (!nd) return <span className={`${cls} stamp--quiet`}>Dates TBA</span>;
  const label =
    nd.kind === "registration"
      ? "Last date"
      : nd.kind === "submission"
        ? status === "live"
          ? "Live · submit by"
          : "Submit by"
        : nd.kind === "end"
          ? status === "live"
            ? "Live · ends"
            : "Ends"
          : regOpen
            ? "Starts"
            : "Reg. closed · starts";
  const tone = status === "live" && nd.kind !== "registration" ? "stamp--live" : nd.kind === "start" ? "stamp--quiet" : "";
  return (
    <span className={`${cls} ${tone}`}>
      {label} · {fmtDate(nd.at, now)}
    </span>
  );
}

export function TimeLeft({ h, now }: { h: Hackathon; now: number }) {
  const nd = nextDeadline(h, now);
  if (!nd) return null;
  const urgent = nd.kind !== "start" && nd.at - now < 3 * DAY;
  const verb = nd.kind === "start" ? "starts in" : "left";
  const text = nd.kind === "start" ? `${verb} ${countdown(nd.at, now)}` : `${countdown(nd.at, now)} ${verb}`;
  return <span className={`time-left${urgent ? " time-left--urgent" : ""}`}>{text}</span>;
}

/** Link that opens a notice in the detail sheet, keeping the current filters. */
export function OpenNoticeLink({ id, className, children }: { id: string; className?: string; children: React.ReactNode }) {
  const location = useLocation();
  const sp = new URLSearchParams(location.search);
  sp.set("h", id);
  return (
    <Link className={className} to={{ pathname: location.pathname, search: `?${sp}` }} state={{ fromBoard: true }}>
      {children}
    </Link>
  );
}

/**
 * Save + "I applied" as perforated tear-off tabs. Applying tears the tab off the
 * notice (it goes to My tabs); the stub left behind carries your mark.
 */
export function TrackTabs({ h, tracked, compact = false }: { h: Hackathon; tracked?: Tracked; compact?: boolean }) {
  const toast = useToast();
  const [tearing, setTearing] = useState(false);
  const status = tracked?.status;
  const saved = status === "saved";
  const committed = status && status !== "saved" && status !== "withdrawn";

  const apply = () => {
    const prev = tracked;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const done = () => {
      tracker.track(h, "applied");
      setTearing(false);
      toast({
        message: "Filed under My tabs as Applied.",
        action: {
          label: "Undo",
          run: () => (prev ? tracker.setStatus(h.id, prev.status) : tracker.untrack(h.id)),
        },
      });
    };
    if (reduce) return done();
    setTearing(true);
    window.setTimeout(done, 430);
  };

  const toggleSave = () => {
    if (saved) {
      tracker.untrack(h.id);
      toast({ message: "Removed from My tabs.", action: { label: "Undo", run: () => tracker.track(h, "saved") } });
    } else {
      tracker.track(h, "saved");
    }
  };

  if (committed) {
    return (
      <div className="tab tab--stub">
        <span className="tab__mark hand">
          <Check size={15} strokeWidth={2.6} aria-hidden="true" /> {STATUS_LABEL[status!]}
        </span>
        <button
          type="button"
          className="tab__undo"
          onClick={() => tracker.setStatus(h.id, "saved")}
          aria-label={`Move ${h.title} back to Saved`}
          title="Move back to Saved"
        >
          <Undo2 size={14} aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        className={`tab tab--save${saved ? " is-on" : ""}`}
        aria-pressed={saved}
        onClick={toggleSave}
        title={saved ? "Saved to My tabs" : "Save to My tabs"}
      >
        {saved ? <BookmarkCheck size={16} aria-hidden="true" /> : <Bookmark size={16} aria-hidden="true" />}
        {!compact && <span>{saved ? "Saved" : "Save"}</span>}
      </button>
      <button type="button" className={`tab tab--applied${tearing ? " is-tearing" : ""}`} onClick={apply} disabled={tearing}>
        I applied
      </button>
    </>
  );
}
