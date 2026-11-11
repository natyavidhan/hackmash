# Design

Hackmash is a **campus notice board for every hackathon**: every platform's listings pinned to one cork board in one format. The world is physical and specific. Notices are paper, the board is cork, the board's warnings are red rubber stamps, and everything the visitor does is in blue ballpoint. It refuses the white SaaS card grid with a purple accent and the neon "hacker" dashboard.

Mode: **Operate**. Scanning, comparing and tracking come first; the world lives in precise details and must never obscure a date, a filter or an action.

Tokens live in `frontend/src/styles/base.css` (`:root`). Use them; don't introduce new colours.

## Colour

Strategy: restrained. A cork field, with paper carrying the content and two inks carrying meaning.

| Role | Token | Value | Use |
|---|---|---|---|
| Board | `--cork` | `#c69259` | Page ground, with the speckle texture `assets/cork.svg` |
| Text on cork | `--cork-ink`, `--cork-ink-2` | `#2e1d0d`, `#3f2a15` | Counts, page titles, column heads placed directly on cork |
| Frame | `--frame` | `#2a1c10` | Walnut header strip |
| Paper | `--paper` | `#fdfcf8` | Hackathon notices, panels, sheets |
| Paper stocks | `--paper-yellow` `--paper-blue` `--paper-green` `--paper-pink` | | The **format** of a listing: ideathon, coding contest, data science, other. Hackathons stay white. Never decorative. |
| Kraft | `--paper-kraft` | `#ead6b3` | Quick-filter slips |
| Ink | `--ink`, `--ink-2`, `--ink-3` | `#1d1712`, `#4f463c`, `#6f665b` | Text: primary, secondary, labels (all ≥ 4.5:1 on paper) |
| Stamp red | `--stamp` | `#c3122b` | The board's warnings only: deadlines, urgency, clashes, paid entry |
| Ballpoint blue | `--pen` | `#1e45c2` | The visitor's own marks: selected filters, Save, I applied, tracker statuses, notes, focus rings |
| Live green | `--live` | `#0f7a45` | Happening now, extensions, good flags |
| Day-glo | `--dayglo` | `#d4ff3a` | "New" stickers, active nav underline, text selection |

**Push pins carry state:** brass is the default, red means closing within 3 days, green means live, blue means in your tabs.

## Type

- **Archivo Variable** (self-hosted, with its width axis) for everything. Titles, stamps and section heads use `font-stretch: 68–74%` at weight 780–850, like notice headlines. Body and UI use normal width at 450–660.
- **Kalam** (Indian Type Foundry) only for the visitor's handwriting: notes, the "Applied ✓" stub, "your tab", empty-state notes, pinned-search label.
- Numbers are always `tabular-nums` (set on `body`).
- Uppercase tracked labels (0.66–0.74 rem, +0.08 em) are for fact labels (`WHEN`, `WHERE`) and section heads, never as a kicker above a heading.

## Components

- **Notice** (`NoticeCard`, `notice.css`). Every notice has the same anatomy on the same baseline: pin, letterhead (platform · organizer), condensed title (3 lines max), deadline stamp plus time left, fact rows (When, Where, Prize with five-step magnitude ramp, Team), labels, then perforated tear-off tabs (Open on platform ↗ | Save | I applied). The whole notice opens the detail sheet through a stretched title link; tabs sit above it.
- **Stamp** (`.stamp`): condensed caps in a 2 px border, slightly rotated (`--tilt`), with a grain mask (`assets/stamp-grain.svg`). Red by default; `--live`, `--quiet` and `--pen` variants.
- **Tear-off tabs**: dashed perforations. "I applied" tears off (the one authored motion) and leaves a stub with a blue handwritten mark and an undo.
- **Notebook page** (`.notebook`): filters on ruled paper with a red margin. Rows sit on the 28 px rule. Facet counts sit right-aligned in `--ink-3`.
- **Slips**: kraft quick-filter tags with a pin, slightly askew. When on, they turn ballpoint wash with a blue pin.
- **Register** (list view): a ruled ledger with a 2 px ink header rule.
- **Planner** (calendar view): a wall planner with paper slips per start and red "N closing" marks.
- **Map** (map view, `MapView`, `map.css`): a printed political map of India pinned to the cork by two brass pins, in the official Survey of India outline. Neighbours are a light ink wash, the sea is paper with three engraved water lines along every coast, state borders are dashed and the national border solid. A condensed caps cartouche ("INDIA", counts) heads it, with the pin-colour key on a row under it. Push pins mark places, never venues: a place is a city with the towns within 50 km ("Delhi NCR"), the same at every zoom and width. One pin for a quiet place, two from 3 events, three from 10, coloured by the most pressing state there (red, then blue, green, brass). Places too close to tell apart at the current zoom share a pin ("19 Mumbai region +2"). The busiest pins get small paper name tags with a count, every pin once zoomed in; the rest show a bare count. The picked place is circled in ballpoint and its tag turns ballpoint wash. Zoom is +/− paper buttons, then drag to move. Printed names (seas, states, neighbours) only appear where there is room and never under a pin or tag, so phones get the bare map.
  - Beside it, a **place slip** (a bottom sheet of at most 55% of the screen under 1020 px, with the page scrolled so the place stays in view above it): the place in condensed headline type, its state and count, any other place sharing its pin, "Show all N on the board", then a ruled list of its notices with the deadline stamp and time left. Closing returns focus to whatever opened it. Before a place is picked the slip is **Where they are**, a ruled ledger of places by count with red "N close this week" marks; on phones it sits under the map.
  - Kraft slips under the map count what a map can't show: online and abroad (they open on the board or in the list), and in-person events that don't say where (they open in the slip). Credits for the map data sit in a line under the map.
- **State picker** (`StateMap`, in the notebook's Where section): India by state on a paper inset, states with hackathons in paper, the rest in a light ink wash, the picked ones in ballpoint wash with a ballpoint border. Counts sit on states big enough to hold them; the checklist under it is the same control for keyboards and screen readers.
- **Sheet** (`DetailSheet`): the notice taken down. A pinned paper card centred over the dimmed board in a `<dialog>` (at most 560 px wide, at least 16 px clear of every edge and always inside the safe area), its body scrolling inside the card while the pin and close button stay put, with a stapled banner photo and a dashed ballpoint "your tab" box for tracking.
- **Tabs in the tracker** (`.tabcard`): perforated top edge (mask). Won is green stock, shortlisted yellow, finished grey.
- **Report card**: a ruled marksheet table, not a hero-metric block.
- **Buttons**: paper with a hairline border (`.btn`), `--ink` for primary actions, `--pen` for the visitor's own actions, ghost buttons on cork.
- **Link-preview poster** (`backend/hackmash/og/poster.html`, 1200×630): one notice filling the frame on cork, chosen from four mocks on 2026-11-11. Letterhead (logo, platform · format, organizer), the condensed title as large as it fits (up to 112 px, cut with "…" past 4 lines), a facts line with icons (when, where, team), the deadline stamp bottom-left and the prize pool (or registrations) large bottom-right, with the pinned wordmark plate top-right. Paper stock follows the format, as on the board. Dates are absolute in the event's own calendar, never countdowns.
  - Provenance: drawn by headless Chromium on the home server from scraped listing data and each event's own logo. The site's default card, `frontend/public/og-default.jpg`, is `docs/promo/github-social-preview.png` (real screenshots of the board) as a JPEG.

## Depth and shape

- Paper corners are 2 px.
- Paper casts a soft, offset shadow onto cork (`--shadow-paper`) and lifts on hover (`--shadow-lift`, `translateY(-3px)` with ±0.3° rotation).
- No glass, gradients on text, coloured side borders or hard offset shadows.

## Motion

- 150–250 ms state transitions on `--ease-out`.
- Authored moments: the tab tearing off, the sheet coming down, the toast slip. No page-load choreography.
- Everything collapses under `prefers-reduced-motion`.

## Layout

- Max width 1480 px, with gutter `clamp(14px, 2.4vw, 28px)`.
- Explore: a 272 px sticky notebook plus an auto-fill grid of notices (min 272 px).
- Map view: the map sheet plus a 300–360 px column for the city slip. Under 1020 px the slip becomes a bottom sheet and the places ledger moves under the map.
- Under 1020 px the notebook becomes a full-height filter sheet. Under 720 px the view toggle goes icon-only and the search placeholder shortens. Under 560 px the Filters button keeps only its icon and count, so the sort menu and four layouts fit beside it. The Map view has no sort menu.

## Browser surfaces

Themed from the palette:

- Selection is day-glo.
- Caret, accent colour and focus ring are ballpoint.
- Scrollbars are walnut on cork, faint ink inside paper.
- Link underlines are offset.
