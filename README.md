<p align="center"><img src="assets/icon.svg" width="72" height="72" alt=""></p>

<h1 align="center">Hackmash</h1>

<p align="center"><strong>Every hackathon from every platform, on one board.</strong></p>

<p align="center">
Devpost, Unstop, Devfolio, MLH, HackerEarth, Hack2skill, DoraHacks, ETHGlobal, lablab.ai, Kaggle and 16 more,
in one format, with filters that help you choose. Apply on the original platform; track what you applied to right here, with no account.
</p>

<p align="center"><a href="https://hackmash.natya.workers.dev"><strong>Open Hackmash →</strong></a></p>

![The Hackmash board: every platform's hackathons as notices pinned to one cork board](docs/screenshots/board.png)

## Why

Hackathons are scattered over dozens of platforms. Indian college events live on Unstop and Devfolio, corporate ones on HackerEarth and Hack2skill, global ones on Devpost and MLH, Web3 on DoraHacks and ETHGlobal, AI on lablab.ai, ML on Kaggle. No platform lists its competitors' events, so students juggle tabs, WhatsApp forwards and spreadsheets, and still miss registration deadlines. Hackmash reads all of them every few hours, puts every event into one format and pins it to one board.

## What it does

**One board, every platform**
- 26 sources (listed below), refreshed every four hours.
- The same event listed on several platforms (for example MLH + Devpost) is merged into one notice with "Also on" links.
- Every notice links straight to the page where you register. Hackmash never sits between you and the apply button.

**One format**
- Dates and times in your timezone, with a countdown to the next date that matters (registration close, submission, start or end).
- Prize pools in your chosen currency at the day's exchange rate (INR, USD, EUR, GBP, CAD, AUD, SGD), plus a five-step prize-size ramp.
- The same fields for every platform: mode, place, team size, who can join, entry fee, registrations so far. Unknown values are shown as unknown, never guessed.

**Filters that matter**
- Status: open for registration, happening now, not started yet, ended recently.
- Closing within 3, 7, 14 or 30 days. Start date range.
- Online, in person or hybrid. Region and country.
- Platform. 24 themes (AI & ML, Web3, FinTech, HealthTech, Climate, Social Good…).
- Prize pool size. Format: hackathon, ideathon/pitch, coding contest, data science.
- Who it's for: college students, high school, women & non-binary, professionals, startups.
- Your team size (hides events whose limits rule your team out).
- Beginner-friendly, free entry, travel reimbursed, posted this week, offers jobs or internships, clear of your busy dates.
- Facet counts update live as you filter. Every filter lives in the URL, so a search is shareable.
- Quick filter slips, pinned searches, and "hide this notice" to clear what you don't care about.

**Board, list and calendar views**
- Board for browsing, a dense register for scanning, and a month planner showing what starts and which registrations close on each day.
- Press <kbd>/</kbd> to search.

**My tabs (the tracker)**
- Press **I applied** on a notice and its tab tears off into My tabs. **Save** keeps something for later.
- Statuses: Saved → Applied → Submitted → Shortlisted → Won / Didn't place / Dropped.
- A diary of upcoming deadlines (registration for saved events, submissions for applied ones), with urgent ones in red.
- Clash warnings when two intense events overlap, and a monthly count of hacking hours so you don't book every weekend before exams.
- Busy dates (exams, trips, fests): events that clash are flagged on the board, in the notice and in your diary, and the board can hide them.
- Per-hackathon checklist (rules read, team, repo, demo video, deck, submitted), notes, team, project link, and what you won.
- A report card (applied, submitted, won, prize money) and one-click résumé lines: your hackathons, results and project links as Markdown for your CV or LinkedIn.
- Calendar: add any notice to Google Calendar, download an `.ics` with reminders 2 days and 3 hours before each deadline, or subscribe to a live feed of all your tabs.
- Private by design: no accounts. Everything lives in your browser's localStorage. Export/import a JSON backup to move devices, or share a list link with teammates.

**Honest data**
- Paid-entry and invite-only events are flagged; invite-only and test events are left off the board.
- Deadline extensions are detected between refreshes and shown as "Deadline extended", with the old date.
- Hiring challenges (PPOs, internships, placement interviews) are labelled so you know what you're signing up for.
- For Indian winners, a note that cash prizes over ₹10,000 usually have 30% TDS deducted.
- When a platform stops listing an event it is marked and leaves the board, but it stays in your tabs.
- Every notice shows where it came from and when it was last checked. The [Sources](#platforms) page shows each platform's health.

**Public API**
- `GET /api/hackathons` with the same filters. Interactive docs at `/api/docs`.

<p align="center">
<img src="docs/screenshots/notice.png" width="49%" alt="A notice opened up close: stamps, facts, warnings and your own tracking notes">
<img src="docs/screenshots/tracker.png" width="49%" alt="My tabs: report card, deadline diary with clash warnings, and a board of tracked hackathons">
</p>

## Platforms

| Region | Platform | Known for |
|---|---|---|
| India | [Unstop](https://unstop.com/hackathons) | India's largest student hackathon and competition platform (formerly Dare2Compete) |
| India | [Devfolio](https://devfolio.co/hackathons) | Indian college hackathons and Ethereum events (ETHIndia, HackThisFall…) |
| India | [HackerEarth](https://www.hackerearth.com/challenges/) | Corporate hackathons and hiring challenges |
| India | [Hack2skill](https://hack2skill.com/hackathons-listing) | Google, government and corporate hackathons in India |
| India | [TechGig](https://techgig.com/hackathons) | Corporate AI hackathons by The Economic Times |
| India | [Reskilll](https://reskilll.com/allhacks) | Corporate and brand hackathons |
| India | [Devnovate](https://devnovate.co/events) | Hack With India city hackathons and college events |
| India | [Commudle](https://www.commudle.com/hackathons) | Community-run developer hackathons |
| Global | [Devpost](https://devpost.com/hackathons) | The biggest global hackathon platform |
| Global | [Major League Hacking](https://www.mlh.com/events) | Official student hackathon league (MLH member events) |
| Global | [Hack Club](https://hackathons.hackclub.com/) | High-school hackathons worldwide |
| Global | [Luma](https://luma.com/discover) | City tech and AI hackathons (SF, NYC, London, Bengaluru…) |
| Global | [Google Developer Groups](https://gdg.community.dev/events/) | Hackathons run by GDG chapters |
| Global | [Hackathon.com](https://www.hackathon.com/) | Corporate innovation challenges (BeMyApp) |
| Global | [AngelHack](https://angelhack.com/events/) | Corporate and Web3 hackathons |
| Global | [Hackster.io](https://www.hackster.io/contests) | Hardware and embedded build contests |
| Global | [DoraHacks](https://dorahacks.io/hackathon) | The largest Web3 hackathon platform |
| Global | [ETHGlobal](https://ethglobal.com/events) | Ethereum hackathons, in person and online |
| Global | [TAIKAI](https://taikai.network/hackathons) | Corporate, EU-programme and Web3 hackathons |
| Global | [HackQuest](https://www.hackquest.io/hackathons) | Web3 ecosystem hackathons and buildathons |
| Global | [Encode Club](https://www.encodeclub.com/programmes) | Web3 and AI hackathons with ecosystem partners |
| Global | [AKINDO](https://app.akindo.io/wave-hacks) | Web3 WaveHack grant sprints |
| Global | [lablab.ai](https://lablab.ai/ai-hackathons) | AI hackathons with AI companies |
| Global | [Kaggle](https://www.kaggle.com/competitions) | Machine-learning competitions |
| Global | [Zindi](https://zindi.world/competitions) | Data-science competitions for Africa and the Global South |
| Global | [DrivenData](https://www.drivendata.org/competitions/) | Social-impact ML competitions |

How each platform is read, and the ones that could not be added (login walls, JavaScript-only pages, defunct sites), is documented in [docs/platforms.md](docs/platforms.md).

## How it works

```
 26 platform adapters          pipeline                          serving
┌──────────────────┐   ┌──────────────────────────────┐   ┌──────────────────────────────┐
│ devpost.py       │   │ merge into state             │   │ /data/catalog.json  (static) │
│ unstop.py        │──▶│ normalise: themes, audience, │──▶│ React app filters it locally │
│ devfolio.py  …   │   │   country, currency → USD    │   │ /api/* FastAPI: search, ICS, │
│ (Python, httpx)  │   │ dedupe across platforms      │   │   sources, health            │
└──────────────────┘   │ publish catalog snapshot     │   └──────────────────────────────┘
                       └──────────────────────────────┘
```

- **Backend (Python 3.12, FastAPI)**, in `backend/hackmash/`:
  - `sources/`: one adapter per platform. Each uses that platform's public JSON API, embedded page data (`__NEXT_DATA__`, JSON-LD) or HTML.
  - `normalize.py`: canonical themes, audiences, countries and regions, plus currency conversion.
  - `dedupe.py`: fuzzy title + date matching across platforms.
  - `pipeline.py`: concurrent fetching with per-source timeouts. A failing source keeps its last good listings.
  - `catalog.py`: builds the published snapshot.
  - `api.py`: the HTTP routes.
- **State** is one JSON document (`state.json.gz`) holding listings with first/last-seen times and per-source run logs. It can live in a local folder or travel between CI runs.
- **Frontend (React 19, TypeScript, Vite)**, in `frontend/`. It downloads the catalog once (about 150 KB gzipped) and filters in the browser, so filtering is instant and hosting costs almost nothing. The tracker is `localStorage` only.

## Run it locally

Needs [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
# 1. backend: fetch every platform, then serve the API + built web app on :8000
cd backend
uv sync
uv run hackmash refresh          # ~1–2 minutes; prints a line per platform
uv run hackmash serve            # http://127.0.0.1:8000  (re-fetches every 4 h by itself)

# 2. frontend, in another terminal (hot reload on :5173, proxies /api and /data to :8000)
cd frontend
npm install
npm run dev

# production build: the backend serves frontend/dist automatically
npm run build
```

Settings (environment variables): `HACKMASH_REFRESH_HOURS` (default 4), `HACKMASH_AUTO_REFRESH=0` to disable the background refresher, `HACKMASH_DATA_DIR`, `HACKMASH_STATIC_DIR`, `HACKMASH_ADMIN_TOKEN` (enables `POST /api/admin/refresh`), and `KAGGLE_USERNAME` / `KAGGLE_KEY` (enable the Kaggle adapter).

### CLI

```bash
uv run hackmash sources            # list adapters
uv run hackmash fetch unstop       # run one adapter: item count, field coverage, problems, samples
uv run hackmash fetch unstop --json
uv run hackmash refresh devpost mlh   # fetch some (or all) sources and publish the catalog
uv run hackmash rebuild            # re-publish the catalog from saved state, no fetching
uv run pytest                      # tests
```

### API

| Endpoint | What it returns |
|---|---|
| `GET /data/catalog.json` | The whole snapshot the web app uses (ETag-cached) |
| `GET /api/hackathons?q=&source=&mode=&theme=&country=&status=&min_prize_usd=&beginner=&free=&sort=&page=` | Filtered, sorted, paginated listings |
| `GET /api/hackathons/{id}` | One listing, with status, `registration_open` and `next_deadline` |
| `GET /api/hackathons/{id}/calendar.ics` | The event plus registration/submission deadlines, with reminders |
| `GET /api/calendar.ics?ids=a,b,c` | A subscribable calendar for a list of hackathons |
| `GET /api/sources` | Platforms and their fetch health |
| `GET /api/docs` | Interactive OpenAPI docs |

## Adding a platform

Create `backend/hackmash/sources/<key>.py` with a `Source` subclass. It is discovered automatically.

```python
class MyPlatform(Source):
    key = "myplatform"
    name = "My Platform"
    homepage = "https://myplatform.example/hackathons"
    region = "global"            # or "india"
    focus = "One-line summary"

    async def fetch(self, client) -> list[RawHackathon]:
        data = await get_json(client, "https://myplatform.example/api/hackathons")
        return [RawHackathon(source=self.key, source_id=str(r["id"]), title=r["name"], url=r["url"],
                             starts_at=to_utc(r["start"]), ...) for r in data]
```

Run `uv run hackmash fetch myplatform` until it reports "no problems found", and spot-check a few items against the live site. `sources/devpost.py` is a complete reference adapter. `sources/base.py` has helpers for retries, bounded concurrency, dates, money and text.

## Deploying to Cloudflare Workers

Everything runs on Cloudflare's edge:

- **Static assets.** The React app and `/data/catalog.json` are served directly by Workers static assets, with no server work per visit.
- **Python Worker.** `worker/src/entry.py` runs the same FastAPI routes on Python Workers for `/api/*`.
- **Scraper.** A [scheduled GitHub Action](.github/workflows/refresh.yml) runs the Python scrapers every four hours, carries the state over from the live site, refuses to publish a broken catalog, rebuilds the app and deploys with `pywrangler`. The scraper makes a few hundred outbound requests and needs real CPython, which is why it runs in CI and not inside the Worker.

One-time setup:

1. Create a Cloudflare API token with the *Edit Cloudflare Workers* template.
2. In the GitHub repo, add the secret `CLOUDFLARE_API_TOKEN` and the variable `CLOUDFLARE_ACCOUNT_ID`. The workflow stays off until that variable exists.
3. Run the workflow once (Actions → *Refresh listings and deploy* → Run workflow).
4. Set the repository variable `HACKMASH_URL` to the deployed URL, so later runs carry state over.

Manual deploy from your machine:

```bash
cd backend && uv run hackmash refresh && cd ../frontend && npm run build
mkdir -p dist/data && cp ../backend/data/{catalog.json,state.json.gz} dist/data/
cd ../worker && ./build.sh && npm install && uv run pywrangler deploy
```

## Project layout

```
backend/    Python package `hackmash`: adapters, pipeline, API, CLI, tests
frontend/   React + TypeScript + Vite web app
worker/     Cloudflare Workers entry (Python) and wrangler config
docs/       research on student pain points and the platform landscape
.github/    scheduled refresh-and-deploy workflow
```

## Research behind the features

- [docs/research/student-pain-points.md](docs/research/student-pain-points.md): what students on Reddit, Hacker News and other forums say goes wrong with hackathons (scattered listings, missed deadlines, paid or fake events, eligibility confusion, clashing with exams, team logistics), and which feature here addresses each.
- [docs/platforms.md](docs/platforms.md): the hackathon platforms universities, companies and communities use, in India and globally, and how each is read.

## Responsible fetching

Hackmash reads only public pages and public APIs, a few times a day, with bounded concurrency, retries with backoff and an identifying user agent. It links every listing back to its source and stores no personal data. If you run a platform listed here and want changes, open an issue.

## Credits

Thanks [Sushant](https://github.com/sushant-mishra-dtu/) for the idea.
