# Platforms: how each one is read

Every adapter lives in `backend/hackmash/sources/<key>.py` and is tested with `uv run hackmash fetch <key>`, which reports item count, field coverage and data problems. Counts below are from the first full run (3 Nov 2026). Early November is quiet on many platforms, so small counts reflect the platforms themselves, not missing data.

The wider landscape (who uses which platform, enterprise tools, dead and merged platforms) is in [research/student-pain-points.md](research/student-pain-points.md#part-2-platform-landscape).

## India

| Key | Listings | How it is read | Known gaps |
|---|---|---|---|
| `unstop` | 243 | Public search API (`oppstatus=open` plus `closed`, meaning registration closed but the event isn't over) and each competition's detail JSON | Unstop files almost everything as a coding challenge, so the format (hackathon, ideathon, contest, robotics, CTF) is inferred from title, rounds and tags. Start date is missing when an event has no rounds. In-kind and credit prizes are left out of the cash amount. |
| `devfolio` | 20 | Public GraphQL API: one query for every hackathon not yet ended | Prizes are mostly stored in USD. No organizer field. Entry is always free on Devfolio. |
| `hackerearth` | 3 | Compete and hiring APIs, the extension feed, and each event page's embedded data | Very few public challenges right now. Detail "phase" times can be 5:30 h off, so they aren't used. |
| `hack2skill` | 6 | Public event list API plus event details and T&C | Bootcamps and pop-ups skipped. Registration counts are usually hidden by organizers. |
| `techgig` | 10 | Contest listing filtered to hackathons, plus each hackathon page | Every page has its own template, so team size, themes and eligibility are best-effort. Most prizes say TBA. |
| `devnovate` | 10 | Public events API (about 300 events) | Only approved hackathon-type events. Dates are whole days in IST. Organizer phone numbers and emails in the feed are dropped. |
| `reskilll` | 1 | Listing cards plus each event's JSON-LD | Only events hosted on Reskilll itself are parsed. |
| `commudle` | 1 | Public hackathons API (future, plus recent past to catch running events) | Reads one large "past" page, about 7 s. |

## Global: students and communities

| Key | Listings | How it is read | Known gaps |
|---|---|---|---|
| `devpost` | 169 | Public hackathon list API (40 per page), then each hackathon page's JSON-LD for exact times, address and prize currency | About 40 s for the detail pages. |
| `mlh` | 66 | The current season's events page (season 2027), whose events are embedded as JSON | No prizes, descriptions or organizer. The link is the event's own website. Events with no times set get local midnight and end of day. |
| `hackclub` | 14 | Public API for upcoming events | Times are entered by organizers as UTC and are sometimes really local time, so dates are reliable and times approximate. Hack Club is credited, as its API terms ask. |
| `luma` | 39 | Anonymous city feeds behind Luma's Discover pages (87 cities, throttled), filtered to hackathons, buildathons and game jams | Only events Luma features per city, so online-only ones are mostly missed. Bursts get rate-limited; a blocked run keeps the previous listings. |
| `gdg` | 43 | Monthly event sitemaps plus each event page, one at a time with the 2 s delay robots.txt asks for (its `/api/` is disallowed) | About 95 s. Events that began in an earlier month and are still running are missed. The site defaults unknown countries to "US", so the country is taken from the event's timezone instead. |
| `hackathoncom` | 3 | Hackathon.com listings, re-timed with each event's country timezone (also covers BeMyApp) | Some end dates differ from the organizer's own site. |
| `angelhack` | 1 | Events page cards | Dates only. |
| `hackster` | 3 | Contest data embedded in the listing page (exact Pacific times) | Detail pages sit behind bot protection, so only the top prize is known. |
| `kaggle` | 30 | The JSON endpoint Kaggle's own site uses (no login) | Undocumented, so it could change. Tutorials and class competitions are excluded. Set `KAGGLE_USERNAME`/`KAGGLE_KEY` only if that route ever closes. |
| `hackerrank` | (off) | Contest REST API | **Disabled**: HackerRank's robots.txt disallows `/rest/` and `/contests/`. The adapter is kept for reference. |

## Global: Web3, AI and data science

| Key | Listings | How it is read | Known gaps |
|---|---|---|---|
| `dorahacks` | 11 | Public hub API (ongoing and upcoming) plus a detail call per event | No registration deadline, team size or eligibility. Token prizes (e.g. ADA) are shown as text only. |
| `ethglobal` | 1 | Data embedded in the events page and each event page, with exact times taken from the event schedule | Event pages currently answer HTTP 500 while still carrying full data; the adapter accepts that. |
| `taikai` | 2 | Public GraphQL API, challenges with a timeline step still ahead | No mode or venue field; mode is set only when the text says so. |
| `lablab` | 2 | Data embedded in the AI-hackathons page plus each event page | No registration or submission deadlines. The prize is read from page text, which is fragile. |
| `encode` | 2 | The site's public read-only database API (programmes, prize tracks, venues) | Venue comes as one address string. |
| `akindo` | 3 | Public WaveHack and hackathon APIs | A WaveHack is listed by its current wave (dates and grant for that wave). |
| `hackquest` | 1 | Public GraphQL API | Venue is free text. Prize pools in mixed currencies get no amount. |
| `zindi` | 5 | Public competitions API plus details | "Points" rewards count as non-cash prizes. |
| `drivendata` | 1 | Active prize-competition cards | Practice and benchmark competitions are skipped. |

## Investigated and left out

| Platform | Why |
|---|---|
| Eventbrite | Search API removed; everything else needs OAuth, and its terms prohibit automated access. |
| MachineHack | Relaunched with one competition, already ended. |
| Analytics Vidhya DataHack | Only perpetual practice problems are active; worth revisiting. |
| KonfHub | Listing API refuses requests from outside its app; mostly conferences. |
| GeeksforGeeks | Events API lists only webinars and workshops. |
| Smart India Hackathon | One annual event whose dates exist only in free-text notices; better as a hand-curated entry. |
| Superteam Earn | Its "hackathons" are sponsor side-tracks of other hackathons; none open now. |
| Colosseum | Two hackathons a year, no structured data; the current one is in judging. |
| Gitcoin | No longer runs hackathons (grant rounds only). |
| AIcrowd | No live prize challenges; the "active" list is perpetual benchmarks. |

## Worth adding next

- **Coding contests** (all public JSON): CodeChef, Codeforces, AtCoder, LeetCode.
- **Knowafest**: an aggregator of Indian college-fest hackathons (expect overlap with Unstop).
- **NASA Space Apps**: hundreds of local events once a year.
- **Specific Luma calendars** (Cerebral Valley, AGI House, AI Tinkerers) for hackathons Luma doesn't feature.
- **BeWater**: an Asian Web3 platform; it timed out from our network, so retry.
- **Codabench / CodaLab** for ML challenges.
