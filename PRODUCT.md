# Product

<!-- impeccable:product-schema 1 -->

> Facts marked *(inferred)* come from the founder's written brief, not an interview; confirm or correct them.

## Platform

web

## Stack

User-specified: Python backend (FastAPI; scrapers + normalisation + API), React frontend (Vite + TypeScript). Deploy target: Cloudflare Workers.

## Users

Primary: college students in India and abroad who take part in hackathons, plus high-school students and early-career developers *(inferred)*. They juggle events spread over many platforms (Devpost, Unstop, Devfolio, MLH, HackerEarth, DoraHacks…), decide which ones are worth their weekend, and need to keep track of the ones they applied to.

## Product Purpose

Hackmash lists every current public hackathon from every major platform in one consistent format, with filters to find the right ones. Applying always happens on the original platform. A personal tracker ("I applied", status, notes) lives in the browser with no account. Success: a student finds relevant hackathons in under a minute and never misses a deadline for the ones they are in *(inferred)*.

## Positioning

No single platform lists its competitors' events. Hackmash aggregates across all of them, normalises the data (dates in your timezone, prizes in one currency, mode, eligibility, team size), merges duplicates listed on several platforms, and adds a private tracker that needs no sign-up.

## Operating Context

- Browsed on laptops and phones in short sessions between classes or late at night; deadlines are re-checked often *(inferred)*.
- Every listing hands off to its source platform for applying.
- Tracker data lives in localStorage on one device; export/import moves it between devices.
- Listings refresh from the source platforms every few hours.

## Capabilities and Constraints

- No authentication; personal data stays in localStorage.
- Field coverage varies by platform; unknown values are shown as unknown, never guessed.
- Sources are whatever the adapters in `backend/hackmash/sources/` support.

## Brand Commitments

- Name: **Hackmash** (founder-named).
- `assets/icon.svg` (purple #9333ea rounded square, white "H") looks like a scaffold placeholder, not a confirmed brand asset *(inferred)*.

## Evidence on Hand

- Real, live hackathon listings from the source platforms.
- No testimonials, user numbers, partnerships or press exist; never fabricate them.

## Product Principles

1. One click to the source: Hackmash never stands between a student and the apply button.
2. One format: every platform's listing reads the same, in the user's timezone and currency.
3. Deadlines first: the most time-sensitive fact is always the most visible one.
4. Honest data: show provenance and freshness, flag paid entry and invite-only, admit unknowns.
5. Private by default: tracker data never leaves the browser unless the user exports it.

## Accessibility & Inclusion

WCAG 2.2 AA baseline; works well on low-end Android phones and slow connections (small payloads, no heavy media) *(inferred)*.
