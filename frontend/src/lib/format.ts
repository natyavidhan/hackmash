import type { Hackathon } from "./types";

const LOCALE = "en-GB"; // "12 Nov" reads the same everywhere

const dDM = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" });
const dDMY = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" });
const dWDM = new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short" });
const dTime = new Intl.DateTimeFormat(LOCALE, { hour: "numeric", minute: "2-digit", hour12: true });
const dMonth = new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" });

const sameYear = (a: number, b: number) => new Date(a).getFullYear() === new Date(b).getFullYear();

export function fmtDate(ms: number, now = Date.now()): string {
  return sameYear(ms, now) ? dDM.format(ms) : dDMY.format(ms);
}

export function fmtDay(ms: number): string {
  return dWDM.format(ms);
}

export function fmtTime(ms: number): string {
  return dTime.format(ms).replace(" ", " ");
}

export function fmtDateTime(ms: number, now = Date.now()): string {
  const day = sameYear(ms, now) ? dWDM.format(ms) : dDMY.format(ms);
  return `${day}, ${fmtTime(ms)}`;
}

export function fmtMonth(ms: number): string {
  return dMonth.format(ms);
}

/** "14–16 Nov", "28 Nov – 2 Dec", "30 Dec 2026 – 3 Jan 2027". */
export function fmtRange(start?: number, end?: number, now = Date.now()): string {
  if (!start && !end) return "Dates not announced";
  if (!start) return `Until ${fmtDate(end!, now)}`;
  if (!end || Math.abs(end - start) < 20 * 3_600_000) return fmtDate(start, now);
  const s = new Date(start);
  const e = new Date(end);
  if (s.getFullYear() !== e.getFullYear()) return `${dDMY.format(start)} – ${dDMY.format(end)}`;
  const tail = sameYear(end, now) ? "" : ` ${e.getFullYear()}`;
  if (s.getMonth() === e.getMonth()) return `${s.getDate()}–${e.getDate()} ${dDM.format(end).split(" ")[1]}${tail}`;
  return `${dDM.format(start)} – ${dDM.format(end)}${tail}`;
}

/** Compact time-until: "3d 4h", "5h 20m", "12m". */
export function countdown(ms: number, now = Date.now()): string {
  const diff = ms - now;
  if (diff <= 0) return "now";
  const m = Math.floor(diff / 60_000);
  const d = Math.floor(m / 1440);
  const h = Math.floor((m % 1440) / 60);
  if (d >= 60) return `${Math.round(d / 30)} mo`;
  if (d >= 14) return `${Math.round(d / 7)} wk`;
  if (d >= 1) return h ? `${d}d ${h}h` : `${d}d`;
  if (h >= 1) return `${h}h ${m % 60}m`;
  return `${Math.max(1, m)}m`;
}

export function relativeAgo(ms: number, now = Date.now()): string {
  const m = Math.round((now - ms) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function fmtDuration(hours?: number): string | undefined {
  if (!hours || hours <= 0) return undefined;
  if (hours < 72) return `${Math.round(hours)} h`;
  const days = hours / 24;
  if (days < 21) return `${Math.round(days)} days`;
  if (days < 75) return `${Math.round(days / 7)} weeks`;
  return `${Math.round(days / 30)} months`;
}

/** UTC offset (minutes) of an IANA zone at an instant, or undefined if unknown. */
export function tzOffset(tz: string, at: number): number | undefined {
  try {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
        .formatToParts(at)
        .map((p) => [p.type, p.value]),
    );
    const asUtc = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour % 24, +parts.minute);
    return Math.round((asUtc - at) / 60_000);
  } catch {
    return undefined;
  }
}

export function timeZoneLabel(): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(new Date());
    const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    const iana = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (iana === "Asia/Kolkata" || iana === "Asia/Calcutta") return "IST";
    return name || iana;
  } catch {
    return "local time";
  }
}

// ---------------------------------------------------------------------------
// Money
// ---------------------------------------------------------------------------

export const CURRENCIES = ["INR", "USD", "EUR", "GBP", "CAD", "AUD", "SGD"] as const;

const FALLBACK_FX: Record<string, number> = { USD: 1, INR: 0.0114, EUR: 1.16, GBP: 1.33, CAD: 0.72, AUD: 0.66, SGD: 0.77 };

export function guessCurrency(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (tz === "Asia/Kolkata" || tz === "Asia/Calcutta") return "INR";
    if (tz.startsWith("Europe/London")) return "GBP";
    if (tz.startsWith("Europe/")) return "EUR";
    if (tz.startsWith("Australia/")) return "AUD";
    if (tz === "Asia/Singapore") return "SGD";
    if (["America/Toronto", "America/Vancouver", "America/Edmonton", "America/Winnipeg", "America/Halifax"].includes(tz)) return "CAD";
  } catch {
    /* fall through */
  }
  return (navigator.language || "").endsWith("-IN") ? "INR" : "USD";
}

export function fmtMoney(amount: number, currency: string, compact = false): string {
  const isINR = currency === "INR";
  const locale = isINR ? "en-IN" : "en-US";
  const big = isINR ? amount >= 100_000 : amount >= 1_000_000;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: compact || big ? 1 : 0,
      minimumFractionDigits: 0,
      notation: compact || big ? "compact" : "standard",
    }).format(amount);
  } catch {
    return `${Math.round(amount).toLocaleString()} ${currency}`;
  }
}

export interface PrizeParts {
  main?: string;
  alt?: string;
  usd?: number;
}

export function prizeParts(h: Hackathon, pref: string, fx?: Record<string, number>): PrizeParts {
  const rates = { ...FALLBACK_FX, ...(fx ?? {}) };
  if (h.prize_amount && h.prize_currency) {
    const main = fmtMoney(h.prize_amount, h.prize_currency);
    let alt: string | undefined;
    if (h.prize_currency !== pref && h.prize_usd && rates[pref]) {
      alt = `≈ ${fmtMoney(h.prize_usd / rates[pref], pref, true)}`;
    }
    return { main, alt, usd: h.prize_usd };
  }
  if (h.prize_text) return { main: h.prize_text };
  if (h.non_cash_prizes) return { main: "Non-cash prizes" };
  return {};
}

/** Fixed five-step magnitude ramp for prize pools (USD). */
export function prizeMagnitude(usd?: number): number {
  if (!usd || usd <= 0) return 0;
  if (usd < 1_000) return 1;
  if (usd < 10_000) return 2;
  if (usd < 50_000) return 3;
  if (usd < 250_000) return 4;
  return 5;
}

export function teamLabel(h: Hackathon): string | undefined {
  const lo = h.team_size_min;
  const hi = h.team_size_max;
  if (!lo && !hi) return undefined;
  if (lo && hi) return lo === hi ? (lo === 1 ? "Solo" : `${lo} people`) : `${lo}–${hi} people`;
  if (hi) return hi === 1 ? "Solo" : `Up to ${hi}`;
  return `${lo}+ people`;
}

export function placeLabel(h: Hackathon): string {
  if (h.mode === "online") return "Online";
  const where = [h.city, h.country].filter(Boolean).join(", ") || h.location || "Venue not listed";
  return h.mode === "hybrid" ? `${where} + online` : where;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}
