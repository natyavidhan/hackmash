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
- **Sheet** (`DetailSheet`): the notice taken down. A pinned paper card centred over the dimmed board in a `<dialog>` (at most 560 px wide, 16 px clear of every edge), its body scrolling inside the card while the pin and close button stay put, with a stapled banner photo and a dashed ballpoint "your tab" box for tracking.
- **Tabs in the tracker** (`.tabcard`): perforated top edge (mask). Won is green stock, shortlisted yellow, finished grey.
- **Report card**: a ruled marksheet table, not a hero-metric block.
- **Buttons**: paper with a hairline border (`.btn`), `--ink` for primary actions, `--pen` for the visitor's own actions, ghost buttons on cork.

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
- Under 1020 px the notebook becomes a full-height filter sheet. Under 720 px the view toggle goes icon-only and the search placeholder shortens.

## Browser surfaces

Themed from the palette:

- Selection is day-glo.
- Caret, accent colour and focus ring are ballpoint.
- Scrollbars are walnut on cork, faint ink inside paper.
- Link underlines are offset.
