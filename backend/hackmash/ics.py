"""iCalendar (RFC 5545) export: the event itself plus deadline reminders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

PRODID = "-//Hackmash//Hackathon Calendar//EN"


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold to 75 octets per RFC 5545 §3.1."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += b
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _alarm(trigger: str, text: str) -> list[str]:
    return ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(text)}", f"TRIGGER:{trigger}", "END:VALARM"]


def _event(uid: str, summary: str, start: datetime, end: datetime, item: dict, alarms: list[list[str]]) -> list[str]:
    details = [item.get("tagline") or ""]
    facts = [f"Listed on {item.get('source_name') or item.get('source')}"]
    if item.get("prize_text"):
        facts.append(f"Prizes: {item['prize_text']}")
    if item.get("organizer"):
        facts.append(f"By {item['organizer']}")
    details.append(" · ".join(facts))
    details.append(item.get("url", ""))
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}@hackmash",
        f"DTSTAMP:{_fmt(datetime.now(timezone.utc))}",
        f"DTSTART:{_fmt(start)}",
        f"DTEND:{_fmt(end)}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(chr(10).join(d for d in details if d))}",
        f"URL:{item.get('url', '')}",
    ]
    if item.get("location"):
        lines.append(f"LOCATION:{_escape(item['location'])}")
    for alarm in alarms:
        lines.extend(alarm)
    lines.append("END:VEVENT")
    return lines


def events_for(item: dict) -> list[str]:
    title = item.get("title", "Hackathon")
    hid = item["id"]
    start, end = _parse(item.get("starts_at")), _parse(item.get("ends_at"))
    reg = _parse(item.get("registration_deadline"))
    sub = _parse(item.get("submission_deadline"))
    lines: list[str] = []
    if start:
        lines += _event(
            hid, title, start, end if end and end > start else start + timedelta(hours=1), item,
            [_alarm("-P1D", f"{title} starts tomorrow")],
        )
    if reg:
        lines += _event(
            f"{hid}-registration", f"Registration closes: {title}", reg - timedelta(minutes=30), reg, item,
            [_alarm("-P2D", f"Registration for {title} closes in 2 days"),
             _alarm("-PT3H", f"Registration for {title} closes soon")],
        )
    if sub and (not end or abs((sub - end).total_seconds()) > 3600 or not start):
        lines += _event(
            f"{hid}-submission", f"Submission deadline: {title}", sub - timedelta(minutes=30), sub, item,
            [_alarm("-P1D", f"Submission for {title} is due tomorrow"),
             _alarm("-PT3H", f"Submission for {title} is due soon")],
        )
    return lines


def calendar(items: list[dict], name: str = "Hackmash") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for item in items:
        lines += events_for(item)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
