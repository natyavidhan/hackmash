import type { DeadlineKind, Hackathon, Status } from "./types";

/** Mirrors backend `models.lifecycle`: (status, registration open) from dates. */
export function lifecycle(h: Hackathon, now: number): { status: Status; regOpen: boolean } {
  const end = h.end ?? h.subDeadline;
  if (end !== undefined && end < now) return { status: "ended", regOpen: false };
  // registration and submissions both closed days ago: nothing left to join,
  // even if the platform lists a far-off "end" (results, finale) date
  if (isClosedOut(h, now)) return { status: "ended", regOpen: false };
  let regOpen = !h.invite_only;
  if (h.regOpens !== undefined && h.regOpens > now) regOpen = false;
  if (h.regDeadline !== undefined && h.regDeadline <= now) regOpen = false;
  // a platform that stopped listing an event usually closed registration
  if (h.delisted && h.regDeadline === undefined) regOpen = false;
  if (h.start !== undefined && h.start <= now) return { status: "live", regOpen };
  if (!regOpen) return { status: "upcoming", regOpen: false };
  return { status: "open", regOpen: true };
}

export interface NextDeadline {
  kind: DeadlineKind;
  at: number;
}

/** The next date that matters to someone deciding whether to join. */
export function nextDeadline(h: Hackathon, now: number): NextDeadline | undefined {
  if (isClosedOut(h, now)) return undefined;
  const { regOpen } = lifecycle(h, now);
  if (regOpen && h.regDeadline && h.regDeadline > now) return { kind: "registration", at: h.regDeadline };
  if (h.start && h.start > now && !regOpen) return { kind: "start", at: h.start };
  if (h.subDeadline && h.subDeadline > now && (!h.end || Math.abs(h.subDeadline - h.end) > 3_600_000)) {
    return { kind: "submission", at: h.subDeadline };
  }
  if (h.end && h.end > now) {
    const sameAsSubmission = h.subDeadline !== undefined && Math.abs(h.subDeadline - h.end) <= HOUR;
    return { kind: sameAsSubmission ? "submission" : "end", at: h.end };
  }
  if (h.start && h.start > now) return { kind: "start", at: h.start };
  return undefined;
}

export const DAY = 86_400_000;
export const HOUR = 3_600_000;

/** Submissions closed more than two days ago and registration is shut. Mirrors backend `models.closed_out`. */
export function isClosedOut(h: Hackathon, now: number): boolean {
  return h.subDeadline !== undefined && h.subDeadline < now - 2 * DAY && (h.regDeadline === undefined || h.regDeadline < now);
}
