/** iCalendar (RFC 5545): the event plus its deadlines, with reminders. Mirrors backend `hackmash/ics.py`. */

import type { Item } from "./env";
import { ms } from "./lifecycle";

const PRODID = "-//Hackmash//Hackathon Calendar//EN";
const HOUR = 3_600_000;
const encoder = new TextEncoder();

const stamp = (t: number) => new Date(t).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

const escape = (text: string) =>
  text.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

/** Fold to 75 octets per line (RFC 5545 §3.1), never splitting a character. */
function fold(line: string): string {
  if (encoder.encode(line).length <= 75) return line;
  const parts: string[] = [];
  let current = "";
  let size = 0;
  for (const ch of line) {
    const n = encoder.encode(ch).length;
    if (size + n > (parts.length ? 74 : 75)) {
      parts.push(current);
      current = "";
      size = 0;
    }
    current += ch;
    size += n;
  }
  parts.push(current);
  return parts.join("\r\n ");
}

const alarm = (trigger: string, text: string) => [
  "BEGIN:VALARM",
  "ACTION:DISPLAY",
  `DESCRIPTION:${escape(text)}`,
  `TRIGGER:${trigger}`,
  "END:VALARM",
];

function event(uid: string, summary: string, start: number, end: number, item: Item, sourceName: string, alarms: string[][]) {
  const facts = [`Listed on ${sourceName}`];
  if (item.prize_text) facts.push(`Prizes: ${item.prize_text}`);
  if (item.organizer) facts.push(`By ${item.organizer}`);
  const details = [item.tagline ?? "", facts.join(" · "), item.url].filter(Boolean).join("\n");
  const lines = [
    "BEGIN:VEVENT",
    `UID:${uid}@hackmash`,
    `DTSTAMP:${stamp(Date.now())}`,
    `DTSTART:${stamp(start)}`,
    `DTEND:${stamp(end)}`,
    `SUMMARY:${escape(summary)}`,
    `DESCRIPTION:${escape(details)}`,
    `URL:${item.url}`,
  ];
  if (item.location) lines.push(`LOCATION:${escape(item.location)}`);
  for (const a of alarms) lines.push(...a);
  lines.push("END:VEVENT");
  return lines;
}

function eventsFor(item: Item, sourceName: string): string[] {
  const title = item.title || "Hackathon";
  const start = ms(item.starts_at);
  const end = ms(item.ends_at);
  const reg = ms(item.registration_deadline);
  const sub = ms(item.submission_deadline);
  const lines: string[] = [];
  if (start !== undefined) {
    lines.push(
      ...event(item.id, title, start, end !== undefined && end > start ? end : start + HOUR, item, sourceName, [
        alarm("-P1D", `${title} starts tomorrow`),
      ]),
    );
  }
  if (reg !== undefined) {
    lines.push(
      ...event(`${item.id}-registration`, `Registration closes: ${title}`, reg - HOUR / 2, reg, item, sourceName, [
        alarm("-P2D", `Registration for ${title} closes in 2 days`),
        alarm("-PT3H", `Registration for ${title} closes soon`),
      ]),
    );
  }
  if (sub !== undefined && (end === undefined || Math.abs(sub - end) > HOUR || start === undefined)) {
    lines.push(
      ...event(`${item.id}-submission`, `Submission deadline: ${title}`, sub - HOUR / 2, sub, item, sourceName, [
        alarm("-P1D", `Submission for ${title} is due tomorrow`),
        alarm("-PT3H", `Submission for ${title} is due soon`),
      ]),
    );
  }
  return lines;
}

export function calendar(items: Item[], name: string, names: Record<string, string>): string {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    `PRODID:${PRODID}`,
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    `X-WR-CALNAME:${escape(name)}`,
    "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    "X-PUBLISHED-TTL:PT6H",
  ];
  for (const item of items) lines.push(...eventsFor(item, names[item.source] ?? item.source));
  lines.push("END:VCALENDAR");
  return `${lines.map(fold).join("\r\n")}\r\n`;
}
