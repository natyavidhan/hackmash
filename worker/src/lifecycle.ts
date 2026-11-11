/** Status from an event's dates. Mirrors backend `models.lifecycle` and frontend `lib/lifecycle.ts`. */

import type { Item } from "./env";

export type Status = "open" | "upcoming" | "live" | "ended";

const DAY = 86_400_000;

export const ms = (v: unknown): number | undefined => {
  if (typeof v !== "string" || !v) return undefined;
  const t = Date.parse(v);
  return Number.isNaN(t) ? undefined : t;
};

function closedOut(h: Item, now: number): boolean {
  const sub = ms(h.submission_deadline);
  const reg = ms(h.registration_deadline);
  return sub !== undefined && sub < now - 2 * DAY && (reg === undefined || reg < now);
}

export function lifecycle(h: Item, now: number): { status: Status; regOpen: boolean } {
  const end = ms(h.ends_at) ?? ms(h.submission_deadline);
  if ((end !== undefined && end < now) || closedOut(h, now)) return { status: "ended", regOpen: false };
  const opens = ms(h.registration_opens_at);
  const deadline = ms(h.registration_deadline);
  let regOpen = !h.invite_only;
  if (opens !== undefined && opens > now) regOpen = false;
  if (deadline !== undefined && deadline <= now) regOpen = false;
  if (h.delisted && deadline === undefined) regOpen = false;
  const start = ms(h.starts_at);
  if (start !== undefined && start <= now) {
    if (h.mode === "in_person" && deadline === undefined) regOpen = false;
    return { status: "live", regOpen };
  }
  return regOpen ? { status: "open", regOpen: true } : { status: "upcoming", regOpen: false };
}

/** The soonest registration deadline, submission deadline or end still ahead. */
export function nextDeadline(h: Item, now: number): number | undefined {
  const ahead = [ms(h.registration_deadline), ms(h.submission_deadline), ms(h.ends_at)].filter(
    (t): t is number => t !== undefined && t > now,
  );
  return ahead.length ? Math.min(...ahead) : undefined;
}

/** What the API adds to a stored item: its status right now. */
export function enrich(h: Item, now: number, names: Record<string, string>): Item {
  const { status, regOpen } = lifecycle(h, now);
  const next = nextDeadline(h, now);
  return {
    ...h,
    source_name: names[h.source] ?? h.source,
    status,
    registration_open: regOpen,
    next_deadline: next === undefined ? null : new Date(next).toISOString(),
  };
}
