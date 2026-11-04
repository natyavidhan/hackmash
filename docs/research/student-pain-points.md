# Hackmash research: student hackathon pain points and the platform landscape

*Research brief, 2026-11-03. Written for the agents building Hackmash. No code was changed.*

**Method.** reddit.com blocks our crawler, so Reddit was read through the [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive API:

- every r/hackathon post from 2023-01-01 to 2026-11-03 (9,360 posts, about 25.6k comments by archive count);
- every post with "hackathon" in the title in r/csMajors, r/cscareerquestions, r/learnprogramming, r/college, r/webdev, r/ethdev and r/Indian_Academia (2023–2026), and in r/developersIndia (Jun 2024 – Sep 2025, partial).

About 70 threads were read in full, top comments included. Hacker News came through the Algolia API, and dev.to, Medium, Quora, forums, vendor blogs and press through web search. Frequencies are keyword buckets over r/hackathon, so treat them as directional (see Caveats).

---

## Executive summary: top 10 problems and the fix for each

| # | Problem (ranked) | Evidence | What Hackmash ships |
|---|---|---|---|
| 1 | Events are spread over 50+ sites, and students find the good ones after registration closes | About 275 "where do I find…" posts; at least 3 students posted their own aggregators in 2026 | One feed with "Opens soon", "Closing in 72 h" and "New since last visit" views, saved filters, and a calendar feed per filter |
| 2 | Deadline chaos: registration, idea/PPT, submission and results deadlines, time zones, repeated extensions, portals crashing at the cutoff | 378 posts; the SIH portal went down on deadline day; IST users stay up until 5:30 AM for results | Stage timeline in local time with a countdown, the next deadline always on top, calendar alarms, a "deadline changed" badge |
| 3 | Corporate hiring "hackathons" (Flipkart GRiD, Meesho, Myntra, Amazon ML, JPMC CFG…) leave students waiting on opaque rounds and results | 5% of r/hackathon posts but about 29% of all its comments; 128 of its 300 most-discussed threads | A separate "Hiring challenge" type; rounds, cutoffs and promised result dates shown; a tracker stage plus a "result overdue" badge |
| 4 | Finding teammates who stay and do the work | About 1 in 6 r/hackathon posts (16%) is about teams | Team-size and solo filters, a link to the official team channel, a local team roster, a share-a-shortlist link (matchmaking is future work) |
| 5 | "Is it worth it?": prize pools padded with credits, prizes cut after the event, unknown odds, 30% TDS in India | Repeated prize-cut and unpaid-prize threads; HN: "20 sponsors handing out credits" | Cash shown apart from credits, number of prizes, odds, prize-change history, INR net-of-TDS hint |
| 6 | Paid, fake and badly run events: entry fees, hidden food and accommodation charges, certificate mills | Students ask specifically for "no registration fee" events | "Paid entry" and "hidden costs" badges, a free-only toggle, trust signals from listing data, a red-flag explainer |
| 7 | Eligibility confusion: student status, graduation batch, CGPA cutoffs, campus-only, women-only, country bans, age | Comes up again and again with SIH, JPMC CFG, Accenture and Devpost rules | Normalised eligibility chips plus a local profile, giving each listing "Eligible", "Check rules" or "Not eligible" |
| 8 | Students can't travel; reimbursement is tiny next to the real cost; visas take months | "$30 travel reimbursement… $800–1000" cost; LA Hacks visa wait of "months" | Online and near-me filters, travel, accommodation and food badges, a "visa likely needed" hint |
| 9 | Clashes with exams and with other events | SIH clashing with end-semester exams; two hackathons on the same day 4 km apart | Tracker calendar with clash detection, plus local "busy dates" (exam weeks) as a filter |
| 10 | Opaque judging: pitch beats code, AI-generated and pre-built projects win | Among the most-upvoted r/csMajors hackathon posts; Ask HN: "vibe coded submissions" have exploded | Show the rubric and weights, the judges, the rules on pre-existing work and AI, and whether scores are published, as a transparency badge; link past winners |

Also covered below: "beginner-friendly" in name only (#11), results, certificates and prize payouts (#12), resume and portfolio (#13), IP grabs and free labour (#14), burnout (#15), and re-typing the same application (#16).

**Tag legend for the fixes:**

| Tag | Meaning |
|---|---|
| **[client]** | Browser only (localStorage or URL) |
| **[data]** | Scraper, normaliser or API work with no user data; in scope |
| **[content]** | Static copy or guides |
| **[future]** | Needs accounts, user-generated content, messaging or user data stored on the server; out of scope for now |

---

## Part 1: Pain points, ranked by importance

### 1. Hackathons are scattered, and students find the good ones after registration closes

**How often:** about 275 r/hackathon posts (2.9%) match "where/how do I find…" patterns. At least three people posted their own aggregators in 2026 ([Hakku](https://www.reddit.com/r/hackathon/comments/1rtv0l4/), [hackathon-searcher](https://www.reddit.com/r/hackathon/comments/1vmbu1m/), [a third](https://www.reddit.com/r/hackathon/comments/1wmdvpq/)). Every student hits this, and it is Hackmash's core job. **Severity: high.**

- "I was spending way too long digging through Devpost, MLH, and X… Half the time, I'd find out about a good one after registration closed." ([r/hackathon, Mar 2026](https://www.reddit.com/r/hackathon/comments/1rtv0l4/))
- "yall keep mentioning hackathons by flipkart/ meesho etc but i never manage to find any these. where do you find such hackathons?" (47 comments; [r/hackathon, Jul 2026](https://www.reddit.com/r/hackathon/comments/1uuldv6/)). The answers point to Unstop, Commudle, Luma and GDG posts on LinkedIn ([another thread](https://www.reddit.com/r/hackathon/comments/1q9ksbk/)).
- "The landscape is fragmented across a dozen different platforms, university boards, and dead Discord servers." Organisers "post their events on Reddit weeks before they pay to get them listed." ([dev.to, May 2026](https://dev.to/ojapio/top-5-places-to-find-hackathons-in-2026-for-indie-hackers-students-2cja))
- A student sees "Applications are currently closed" on the JPMC Code for Good page and can't tell "whether it is yet to open registration or I missed the registration deadline." ([r/hackathon, 3 Nov 2026](https://www.reddit.com/r/hackathon/comments/1xmimtd/))

**Fix:**
- **[data]** Cover the sources students actually name: hiring challenges on Unstop, HackerEarth and Hack2skill, plus Luma and GDG. Add the gaps listed in Part 2 (TechGig, Colosseum, Superteam Earn, Hackster, SIH, NASA Space Apps, Internshala, Commudle, MachineHack, AIcrowd).
- **[data]** A "not open yet" state for recurring events, e.g. "Last edition opened 12 Aug 2025; expect it again around August." This needs editions linked across years in `dedupe.py`.
- **[client]** "Opens soon", "Closing in 72 h" and "New since your last visit" views. Store the last-visit time and the IDs already seen locally. Keep saved searches in localStorage and in the URL.
- **[data]** A calendar or RSS feed URL per filter, built from the query parameters with no account. Reuse `backend/hackmash/ics.py`.
- **[data]** A hardware theme ("Please add a section for hardware lads too", [Hakku thread](https://www.reddit.com/r/hackathon/comments/1rtv0l4/)).
- **[future]** Email or Telegram alerts for a saved search, which needs stored contact details. A cheap stopgap is public channels for popular filters, e.g. "India · online · free".

### 2. Deadline chaos: many stages, time zones, extensions and portals failing at the last minute

**How often:** 378 posts (4%) mention deadlines or time zones. Every multi-round event spawns "is the portal down?" threads. **Severity: very high:** a missed cutoff loses the whole event.

- SIH 2026: "I was about to submit my project idea but from yesterday the website is down… The deadline was 30th Sept." (25 comments; [r/hackathon](https://www.reddit.com/r/hackathon/comments/1wt2fiu/))
- SIH extended the deadline twice. One problem statement went from "< 50 submissions before first deadline extension" to "350s", and "people who submitted early are literally at disadvantage." ([r/hackathon, Oct 2026](https://www.reddit.com/r/hackathon/comments/1wzybjh/))
- "Being in IST, I stayed awake until around 5:30 AM waiting for the results." ([r/hackathon, Sep 2026](https://www.reddit.com/r/hackathon/comments/1wh5vrv/))
- An entrant missed a submission "by 1 or 2 minutes" ([Atlassian Community](https://community.atlassian.com/t5/App-Central/Submission-late-by-1-minute/ba-p/2242130)). GradHack's organisers kept the portal open "just in case people forget to consider timezones" ([Engineers Australia](https://eaxchange.engineersaustralia.org.au/discussion/your-challenge-has-been-released)).
- "Where do we submit the final ZIP for Amazon ML Challenge 2026 on Unstop?" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1wrgwgz/))

**Fix:**
- **[data]** Model each event as a list of **stages**: registration, idea/PPT, OA, prototype, finale, results. Each stage has opens/closes times, a timezone, a mode and its deliverables. Today the model has only registration, submission, start and end.
- **[client]** The card always shows the *next* cutoff in the user's timezone with a countdown, e.g. "Idea submission closes in 5 h 12 m (23:59 IST)". Show the event's local time as well, and "timezone unknown" when the source gives none.
- **[client]** Make "registration closes before the hackathon starts" impossible to miss (a common Devfolio and MLH pattern).
- **[data]** Compare deadlines between scrapes to show an "Extended: 30 Sep → 15 Oct" badge and a "changed" marker on tracked events.
- **[client]** Tracker calendar export with alarms 7 days, 24 hours and 3 hours before each stage. Add a nudge: "Submit early: portals often crash on the last day."
- **[content]** One paragraph per platform on how submission works. On Devpost a project only counts once it is actually submitted. On Unstop each round has its own upload. On Devfolio a project must be submitted, not just saved.

### 3. Corporate hiring "hackathons": opaque rounds, cutoffs and results

**How often:** the loudest topic, mostly from India. These are online-assessment (OA) and pre-placement-interview (PPI) style challenges: Flipkart GRiD, Meesho ScriptedBy{Her}, Myntra WeForShe, Amazon ML Challenge, JPMC Code for Good, Adobe, TVS Credit E.P.I.C, Accenture, BNP Paribas Innoversité, Code with Cisco. They are 5.3% of r/hackathon posts but about 29% of all its comments (7,388 of 25,587), and 128 of its 300 most-commented threads. **Severity: high:** anxiety, wasted effort, and hidden filters such as CGPA or campus.

- "I haven't received any Shortlist mail, so b4 leaving hopes I wanna check if atleast 1 person received so I can have clarity that I am not selected." (136 comments; [Meesho ScriptedBy{Her} 2.0](https://www.reddit.com/r/hackathon/comments/1ufz9l4/)). Another post: "According to their official timeline the results of round 1… were supposed to be out on 25th June." ([thread](https://www.reddit.com/r/hackathon/comments/1uf8k5s/))
- "3rd round has started and they don't have even released the results… it is showing I am not eligible to take part in round 3 am i rejected??" ([TVS E.P.I.C 8.0](https://www.reddit.com/r/hackathon/comments/1vxx62x/))
- Flipkart GRiD 8.0: the assessment tool "crashed for the 12pm slot… there won't be any retest", and "Their support is saying contact flipkart while flipkart is saying contact hirepro" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1v759kc/)). JPMC CFG picked 2028 graduates "solely on the basis of… cpi… 9.4+" ([thread](https://www.reddit.com/r/hackathon/comments/1vbpmct/)).

**Fix:**
- **[data]** Add `kind = "hiring_challenge"`: OA- or interview-based, where the prize is a PPI, PPO or internship. Students can then include or exclude these.
- **[data]** For each hiring challenge, show:
  - what you can win: PPI, internship or cash;
  - what screens you out: an OA on Unstop, HackerRank or HirePro, an interview, a CGPA cutoff, batch years, campus-only.
- **[data]** Store the official round dates and promised result dates from the listing.
- **[client]** Add a tracker stage picker: Applied → R1 cleared → R2 → Interview → Offer / Waitlist / Rejected. Add a badge like "Result expected 25 Jun · 3 days overdue" and a one-tap link to the official updates page. Add a "close as no response" action after N days.
- **[future]** A crowd-sourced "anyone got the mail?" status per round. This needs user submissions and is open to abuse.

### 4. Finding teammates who stay and do the work

**How often:** about 1 in 6 r/hackathon posts (1,522, 16%) is about teams; 895 have "looking for team/teammates" in the title. **Severity: high**, but Hackmash can only partly fix it.

- "I wrote 100% of the code but split the prize 4 ways. I'm done… We met on the official event Discord. Everyone introduced themselves as 'experienced.'" (61 upvotes; [r/hackathon, Dec 2025](https://www.reddit.com/r/hackathon/comments/1pox3pc/))
- "pls stay away those who ghost after 2 days" (46 comments; [r/hackathon](https://www.reddit.com/r/hackathon/comments/1rv84ll/)). Another student: "no one calls me. Even if I call people they are already attending hackathons with others." ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1o9sawy/))
- SIH requires a female member, and its internal round requires the team leader to be present. One student's female team lead "had another hackathon at the same time." ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1vxg3ig/))

**Fix:**
- **[data]** Team size min/max (the fields exist) and a derived "solo allowed". Add team-composition rules: "at least one woman", "all from one institute", "faculty mentor required".
- **[data]** A "team help at the event" flag, plus a link out to the official team-forming channel (Discord or the Devpost participants page).
- **[client]** A team roster in the tracker (names, roles and handles, stored locally) and task notes.
- **[client]** A "share shortlist" link that puts event IDs in the URL, so a team can look at the same events without accounts.
- **[future]** Teammate matchmaking, profiles, reliability scores and chat. One student built a "Developer Credit Score… so you don't get ghosted" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1pscfep/)).

### 5. "Is it worth it?": prize transparency and odds

**How often:** prize-cut and unpaid-prize threads recur, and Ask HN's ["Hackathons feel fake now"](https://news.ycombinator.com/item?id=43889502) drew 128 comments. **Severity: high:** this decides where a weekend goes.

- "the devpost page advertised 1700 dollars worth of prizes… after the hackathon… they changed it to just 400 dollars" ([r/hackathon, Mar 2024](https://www.reddit.com/r/hackathon/comments/1b7pzr8/)). A hackathon backed by CyberPeace, BPR&D and NCRB reduced its prizes "on the day of the event", and the winners were still unpaid after 9+ months ([r/hackathon, Jul 2026](https://www.reddit.com/r/hackathon/comments/1v0oqaw/)).
- "There are like 20 sponsors handing out credits for their tools that all do the same thing." ([HN](https://news.ycombinator.com/item?id=43889502)) A typical headline: "$300K+ in credits + $2K+ cash prizes" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1s5j0i6/)).
- "I always in search of lesser-known hackathons where 1) Probability of winning is high. 2) There are a large number of winners, not merely a participation certificate." ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1n6f99x/))
- India: FOSS Hack's organisers deduct "30% Tax Deducted at Source (TDS)" under Section 194B on prizes above ₹10,000 ([FOSS United forum](https://forum.fossunited.org/t/foss-hack-2024-results/3964/3)).

**Fix:**
- **[data]** Keep cash in `prize_amount` and record credits, swag and internships separately. Never headline credits as the "prize pool". Offer a "cash ≥ X" filter in the user's currency via `fx.py`.
- **[data]** Count prizes, winners and tracks. Show an odds hint when both numbers are known: registrations ÷ prizes, e.g. "about 1 prize per 40 teams".
- **[data]** Keep a prize snapshot per scrape, to show "Prize pool changed: $1,700 → $400 on 2 Mar".
- **[client]** A tooltip on INR cash prizes: "≈₹70,000 after 30% TDS (applies above ₹10,000)".
- **[content]** Show what is actually won (cash, PPI, travel to the finale) next to the effort it takes (rounds and deliverables, see #14).

### 6. Paid, fake and badly run events

**How often:** 126 scam/fake posts and 98 fee posts, plus many requests for free-only events. Indian college events and tech fests are hit hardest. **Severity: medium to high:** students lose money and trust.

- HackIndia Spark (NIT Delhi): food was promised, then "we were asked to pay mess food charges… Even after paying multiple charges such as registration, food, and accommodation." ([r/hackathon, Apr 2026](https://www.reddit.com/r/hackathon/comments/1swi66n/))
- "Since I'm a student, I'll mainly be participating in free hackathons with no registration fees" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1ws2vpb/)). "Any online hackathons (without any reg fee) coming this week?" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1pys3k4/))
- Red flags listed by an Indian platform: "high registration fees for 'certificates'", "certificates without requiring any submission", "Unknown organizers with no track record" ([Reskilll blog](https://blogs.reskilll.com/online-hackathons-with-free-certificates-in-india-where-to-find-them-in-2026/)).

**Fix:**
- **[data]** A "Paid entry: ₹300/team" badge. The existing `registration_fee` flag needs an amount, a currency, and whether it is per team or per person. Add a one-tap "free only" toggle.
- **[data]** Hidden-cost flags: food or accommodation charged, travel at your own cost, finale attendance mandatory.
- **[data]** A small "listing completeness" meter built only from data (product principle: honest data). Signals: organiser verified on the platform, past editions found, a rules or judging page, itemised prizes, a contact address.
- **[data]** A "Certificate only" badge when there is no cash or other real prize.
- **[content]** A "Why flagged?" popover and a red-flag checklist page.
- **[future]** User reports and ratings of organisers.

### 7. Eligibility confusion

**How often:** 507 posts (5.4%) mention eligibility, and every big Indian event has its own rules. **Severity: medium to high:** wasted applications and disqualifications.

- "Code for good is an on campus opportunity you can only apply if jpmc reaches out to your college" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1xmimtd/)). Another thread title: "Accenture Innovation Challenge – 2026 [Only eligible institutes]" (59 comments; [r/hackathon](https://www.reddit.com/r/hackathon/comments/1w60usm/)).
- SIH says "participants must be from a college". A class-11 student only learned about SIH Junior (classes 6–12) from a reply ([r/developersIndia](https://www.reddit.com/r/developersIndia/comments/1f3vh2z/)). "Should I attend a hackathon at 14?" (70 upvotes; [r/csMajors](https://www.reddit.com/r/csMajors/comments/1h15rer/))
- Devpost rules often exclude whole regions: "Why is Quebec banned by Devpost on the same list as N. Korea and Iran?" ([HN](https://news.ycombinator.com/item?id=32644834)). MLH events often exclude graduates (paraphrase, [dev.to](https://dev.to/ojapio/top-5-places-to-find-hackathons-in-2026-for-indie-hackers-students-2cja)).
- Women-only tracks are common in India (Meesho ScriptedBy{Her}, Myntra WeForShe, Women Who Master) and produce huge threads; the Myntra shortlist thread has 293 comments ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1um8bdp/)).

**Fix:**
- **[data]** Normalised eligibility keys, extending `audience`: students only, professionals allowed, school students (minimum age), graduation years, women only, countries allowed and excluded, campus or invite only, CGPA cutoff, an institute list, team composition.
- **[client]** An optional local profile (country, student or not, graduation year, age band, gender). It gives each listing "Eligible", "Check rules" or "Not eligible", with a "hide ineligible" switch. Filter on the device, or send only the filter parameters, so the profile never reaches the server.
- **[client]** Unknown rules stay "Check rules", with a deep link to the rules section.

### 8. Online or in person: travel cost, accommodation and visas

**How often:** 189 travel posts. Students who can't travel often ask for online-only events. **Severity: medium.**

- "I can't travel to places. Apart from Delhi NCR." ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1s0eqbn/))
- "I got a 30 dollar travel reimbursement… it's just is gonna cost a pretty penny like $800-1000." ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1acpaz1/)) An Odoo 2026 finalist asks: "is it worth traveling such a long distance? Also, do they cover travel and accommodation expenses?" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1vbmq3i/))
- Going to LA Hacks from India: visa "wait times… its like months", and out-of-town hackers are told to bring "sleeping bags" ([r/csMajors](https://www.reddit.com/r/csMajors/comments/1vgetik/)).

**Fix:**
- **[data]** Travel badges: reimbursement (with the cap, if stated), accommodation, meals, "finalists' travel covered".
- **[data]** Geocode the venue to power "Near me", "Within 300 km" and "My country" filters. For hybrid events, show "online round 1 → in-person finale in Gandhinagar".
- **[client]** A "visa likely needed" hint for in-person events outside the user's country, from a simple rule table with a disclaimer. Compare the RSVP or confirm-by date with typical visa waits.

### 9. Clashes with exams and with other events

**How often:** fewer posts (about 20 on exam clashes, 64 on overlaps), but it comes back every semester and every SIH season. **Severity: medium.**

- "SIH24 clashes with my end-semester exams" ([r/Indian_Academia](https://www.reddit.com/r/Indian_Academia/comments/1h0c8d6/)). "coz of my exams i want a hackathon that is gonna held in April" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1r7gyvj/)).
- "Cardano IBW finalist (can't attend cause of exams), final round fot MumbaiHacks (couldn't attend due to exams)" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1p8vulj/))
- "On Aug 23rd there are two hackathons in Hyderabad, just 4 km apart" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1mvjzh6/)). CodeChef extended a deadline after students cited mid-semester exams ([CodeChef Discuss](https://discusstest.codechef.com/t/request-to-extend-the-submission-date-of-the-codechef-api-hackathon/22914)).

**Fix:**
- **[client]** A tracker calendar (month and agenda views) with every stage of the saved events. Warn when two tracked events overlap or their deadlines fall within 24 hours of each other.
- **[client]** Local "busy dates" (exam weeks, travel). Show a "clashes with your exams" badge and offer a "hide clashes" filter.
- **[client]** Filters for date range, month, weekends only, and duration (a 24–48 h build versus a multi-week online event).

### 10. Opaque judging, pitch over code, AI-built and pre-built projects

**How often:** fewer posts (about 110), but they include some of the most-upvoted r/csMajors complaints and several HN threads. The top-scoring hackathon post on r/csMajors since 2023 is ["no way this won a hackathon 😭"](https://www.reddit.com/r/csMajors/comments/1gtrs6y/) (1,641 upvotes). **Severity: medium to high:** it makes people quit.

- "Hackathons are pitch competitions. Nothing is tested or deployed. Nobody reads the code in its entirety." (71 upvotes; [r/csMajors](https://www.reddit.com/r/csMajors/comments/1vdsobu/)) "Some hackathon 'farmers' basically use the same idea again and again" (312 upvotes; [r/csMajors](https://www.reddit.com/r/csMajors/comments/1g75mzt/))
- "if there aer 10k submissions they just take 100 randomly", a reply in a dispute over a published rubric ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1wh5vrv/)). IIIT Delhi's Hack4Impact released results 13 days late: "There should be transparency - clear score listings for all teams" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1s3zh5w/)).
- "With the explosion of vibe coded submissions… it's much harder to judge quality of project" ([Ask HN, Feb 2026](https://news.ycombinator.com/item?id=47077312)). On pre-built projects: "people in India atleast bring pre built projects" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1swi66n/)).

**Fix:**
- **[data]** Show the following, or mark each one unknown: judging criteria and weights, whether judges are named, whether pre-existing work is allowed, the AI-tool policy, and whether scores or feedback are published. Together these make a "Transparency" badge and a "published rubric only" filter.
- **[data]** For recurring events, link last edition's winners or project gallery (Devpost and Devfolio galleries).
- **[future]** Participant reviews of judging fairness.

### 11. "Beginner-friendly" in name only

**How often:** 716 beginner posts (7.6%). The second-highest-scored hackathon post on r/csMajors is a first-timer feeling lost. **Severity: medium:** it drives first-timers away.

- "Hackathon organizers be like 'no prior experience required' and then be requiring prior experience" (476 upvotes; [r/csMajors, Oct 2026](https://www.reddit.com/r/csMajors/comments/1ww96ch/))
- "Went to a hackathon, realized I don't know anything AT ALL… I spent 10 hours trying to set up a da[tabase]" (1,453 upvotes; [r/csMajors](https://www.reddit.com/r/csMajors/comments/1bmzryz/))
- "the biggest challenge wasn't actually the technical stuff – it was coming up with an idea that made any sense" ([r/learnprogramming](https://www.reddit.com/r/learnprogramming/comments/1kyqtd6/)). Research finds hackathons intimidate women and beginners ([ICER 2017, "Hack.edu"](https://pg.ucsd.edu/publications/student-perceptions-of-college-hackathons_ICER-2017.txt)).

**Fix:**
- **[data]** Set `beginner_friendly` only when there is evidence: a beginner track or prize, workshops, mentors, team matching, no OA. List that evidence on the card.
- **[data]** A format and effort chip: "Ideathon (PPT only)", "24–48 h build", "OA/DSA screening", "Multi-week online".
- **[content]** A first-hackathon checklist. For idea starters, link past problem statements (SIH's are public) and winner galleries.

### 12. Results, certificates and prize payouts go missing

**How often:** 215 certificate posts. Payout complaints show up across Devpost, HackerRank, Vercel, Web3 and government-backed events. **Severity: medium.**

- "e-certificates had been dispatched or would be shared shortly. However, I haven't received any certificate" ([Flipkart GRiD 8.0, Nov 2026](https://www.reddit.com/r/hackathon/comments/1xl06kn/))
- "results are delayed indefinitely": an IIIT Naya Raipur online hackathon, still nothing after a month ([r/developersIndia](https://www.reddit.com/r/developersIndia/comments/1i37qah/))
- HackerRank said to "expect 6~8 weeks" for prizes, and seven months later they hadn't arrived ([Codeforces](https://codeforces.net/topic/56363/en3)). Vercel May 2026 winners: "we haven't received any communication" ([Vercel Community](https://community.vercel.com/t/vercel-hackathon-05-2026-awards-they-havent-arrived-yet-mendoza-argentina/45333)).

**Fix:**
- **[client]** Post-event tracker fields: the result, the prize promised (amount and date), whether the payout arrived, whether the certificate arrived (with a link), and a follow-up reminder at 30 or 60 days in the calendar export.
- **[content]** A prize-claim checklist (in India: PAN, bank details, TDS) and a polite follow-up email template.
- **[future]** An organiser payout record built from community reports.

### 13. Turning hackathons into a resume or portfolio

**How often:** 771 "worth it / resume / jobs" posts (8.2%). **Severity: medium.**

- "most people write 'Participated in XYZ Hackathon' – that tells the recruiter nothing" ([Enhancv](https://enhancv.com/blog/hackathon-on-resume)). Recruiters "have seen a thousand 'Built AI chatbot at HackFest 2025' resume lines" ([Techverse](https://techverse-edu.onrender.com/blog/hackathons-not-a-career-strategy)).
- "Should I put down winning a hackathon even if I didn't really contribute much to the project" (226 upvotes; [r/csMajors](https://www.reddit.com/r/csMajors/comments/1as120g/)). "Even after having all the skills, hackathon wins, still of no use!!" ([r/developersIndia](https://www.reddit.com/r/developersIndia/comments/1gvo1jp/))

**Fix:**
- **[client]** For each tracked event, record the role, the tech used, and links to the repo, demo video, project page and certificate.
- **[client]** "Export my hackathon history": a Markdown or JSON resume section and LinkedIn-ready bullets, generated locally.

### 14. Free labour, IP grabs and heavy unpaid deliverables

**How often:** few posts (64), but a strong theme on HN and in academic critique. **Severity: medium.**

- "terms of participation that gave the organisers IP first rights to everything and anything done during them"; "an apparatus for getting essentially free labor out of unsuspecting and gullible nerds" ([HN](https://news.ycombinator.com/item?id=43889502))
- Union Bank's iDEA 2.0 demanded "pitch decks, GitHub repos, live prototypes, and three demo videos" in one round, then gave "zero accommodation" for the finale ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1udeulg/)).
- Sociologists describe hackathons as events that "dupe people into working for free" ([Slashdot / Fast Company](https://news.slashdot.org/story/18/03/20/183240/hackathons-are-dystopian-events-that-dupe-people-into-working-for-free-say-sociologists)). HackerEarth says that in over 95% of its events the IP belongs to the participants (a vendor claim; [HackerEarth](https://www.hackerearth.com/blog/good-bad-overrated)).

**Fix:**
- **[data]** An IP badge: "You keep IP", "Licence to organiser", "Assigned to organiser" or "Unknown", linking to the clause. Parse the rules on the big platforms and curate the top events by hand.
- **[data]** List the deliverables for each stage (PPT, video, repo, prototype), so effort can be weighed against the prize at a glance.

### 15. Burnout and lost sleep

**How often:** 210 posts on burnout or exams. **Severity: medium**; this is a health issue.

- "I ended up staying awake for two nights and basically did everything" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1vxg3ig/)). Another post: "Tired and Regret | My first hackathon experience" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1x6dai1/)).
- "One of the contestants stayed up so late he tore a muscle in his eye" ([HN](https://news.ycombinator.com/item?id=43889502)).

**Fix:**
- **[data]** Show the duration and whether the venue has overnight sleeping space.
- **[client]** A multi-week online filter for students who have classes.
- **[client]** A load warning in the tracker, e.g. "3 events in 10 days".

### 16. Re-typing the same application, and account fatigue

- "And then filling out basically the same application questions again" ([r/hackathon](https://www.reddit.com/r/hackathon/comments/1vmbu1m/)).

**Fix:**
- **[client]** A local "application kit" with copy buttons: a saved bio, links (GitHub, LinkedIn, portfolio), a team blurb, T-shirt size, dietary needs and past-project paragraphs.
- **[client]** Export and import as JSON. Needing no account is a selling point.
- **[future]** Auto-filling applications. It risks breaking the platforms' terms of service, as a commenter warned in the [same thread](https://www.reddit.com/r/hackathon/comments/1vmbu1m/).

---

## Feature recommendations for Hackmash

### Must-have (MVP)

1. **Deadline-first card and stage timeline.** Show the next cutoff in local time with a countdown. Keep registration, submission and results deadlines separate, and support an "opens soon" state. (#1, #2, #3)
2. **Data model additions** (table below): stages, a hiring-challenge type, the fee amount, travel and accommodation, eligibility keys, and cash separated from credits. (#2, #3, #5–#8)
3. **Filters that answer the questions students ask.** Keep them in the URL (shareable) and in localStorage:
   - free only;
   - online, near me, my country;
   - eligible for me, women-only, graduation year;
   - team size and solo allowed;
   - kind: build, ideathon, hiring challenge, data science, coding contest;
   - cash prize ≥ X and travel support;
   - date range, month, weekends only, duration;
   - themes, including hardware;
   - beginner-friendly (with evidence).
4. **Local profile and eligibility badge** (country, student or not, graduation year, age band, optional gender). (#7)
5. **Tracker v1 in localStorage.**
   - Statuses: Interested → Registered → Team formed → Submitted → Shortlisted R1/R2… → Finalist → Won / Lost / Waitlisted / No response.
   - Personal deadlines, notes, team roster and links.
   - A "result expected / overdue" badge.
   - Export and import as JSON.

   (#3, #4, #12)
6. **Calendar export** per event, for the whole tracker and per saved filter: `.ics` files with alarms, via `backend/hackmash/ics.py`. (#1, #2, #9)
7. **Honesty badges:** paid entry (with the amount), hidden costs, invite or campus only, certificate only, credits versus cash, the source and "updated 2 h ago", and unknowns shown as unknown. (#5, #6)
8. **Clash detection and busy dates** in the tracker. (#9)

### Nice-to-have

- Odds hint (registrations ÷ prizes) and the number of winners. (#5)
- A change history from comparing scrapes: prize pool changes and deadline extensions. (#2, #5)
- A transparency badge: rubric and weights, judges, rules on pre-existing work and AI, IP terms. (#10, #14)
- Memory of recurring events, e.g. "last edition opened 12 Aug", with a link to past winners. (#1, #10)
- "New since last visit" and saved searches. (#1)
- A share-shortlist link (event IDs in the URL) for teams. (#4)
- Travel-cost and visa hints, and a geocoded "near me". (#8)
- Portfolio export (Markdown, LinkedIn bullets) and the application kit. (#13, #16)
- India specifics: an INR net-of-TDS hint, SIH internal-to-national stages, batch-year chips.
- Static guides: first hackathon, how submission works on each platform, red flags, a prize-claim checklist, a follow-up email template.
- New sources (see Part 2): TechGig, Colosseum, Superteam Earn, Hackster, SIH, NASA Space Apps, Internshala, Commudle, MachineHack, AIcrowd, Junction.

### Future (needs accounts, user data or messaging; out of scope now)

- Teammate matchmaking, profiles, reliability scores and team chat. (#4)
- Crowd status boards ("anyone got the R1 mail?"), organiser reviews, scam and payout reports. (#3, #6, #12)
- Email, push or Telegram alerts for saved searches, which need stored contacts or push subscriptions. Stopgap: public channels for popular filters. (#1)
- Syncing the tracker across devices, through an account or an end-to-end-encrypted sync code.
- Letting verified organisers claim and correct their listings.
- Auto-filling applications (terms-of-service risk). (#16)

### Suggested data-model additions (`backend/hackmash/models.py`)

| Field | Why |
|---|---|
| `stages: list[{kind, name, opens_at, closes_at, results_at, mode, location, deliverables[]}]` | Multi-round events, result dates, effort (#2, #3, #14) |
| `kind += "hiring_challenge"`; `prize_types: [cash, credits, internship, ppi_ppo, travel, swag]` | Separate OA/PPI challenges; show what is actually won (#3, #5) |
| `credits_value`, `num_prizes`, plus `prize_history[]` snapshots kept by the backend | An honest prize pool and odds (#5) |
| `fee_amount`, `fee_currency`, `fee_per: team \| person`, `hidden_costs: [food, accommodation, travel]` | Paid entry and hidden costs (#6) |
| `accommodation_provided`, `meals_provided`, `travel_cap` (next to the existing `travel_reimbursement`) | Travel decisions (#8) |
| `grad_years[]`, `women_only`, `min_age`, `countries_allowed[]`, `countries_excluded[]`, `campus_only`, `cgpa_min`, `composition_rules[]` | Eligibility (#7) |
| `solo_allowed` (derived), `team_help` | Teams (#4) |
| `judging_criteria`, `judges_listed`, `preexisting_work_allowed`, `ai_policy`, `ip_terms`, `rules_url` | Transparency (#10, #14) |
| `series_id` linking editions across years (in `dedupe.py`) | Recurring-event memory and organiser track record (#1, #6) |

### Competitors worth knowing

- **[HackathonRadar](https://www.hackathonradar.com/)** says it has "1,300+ upcoming hackathons" from about 51 platforms read daily.
  - It scores each event's quality: prize credibility, organiser history, completeness, judging transparency.
  - It has student, beginner, remote and cash-prize filters, plus an API and an MCP server.
  - Its homepage shows no travel, fee or team-size filters and no application tracker. These are Hackmash's openings, along with India-first data: hiring rounds, batch eligibility, fees, women-only events.
- **Other aggregators:**
  - [Hakku](https://tryhakku.vercel.app/), which you browse by swiping;
  - Hackamaps, a community-curated map;
  - the Hack Club directory, for high schoolers;
  - Indian list sites: Reskilll, StartupGrantsIndia, Whereuelevate, Internshala.
- **Dead links still recommended:** hackathon.io is now a parked domain and Hackalist is an archive (2014–2025), but older guides still send students to both.

---

## Part 2: Platform landscape

"In repo" means an adapter already exists in `backend/hackmash/sources/`.

### Public listing and hosting platforms

| Platform | Known for | Region | Typical hosts | Public? | In repo | Status and notes |
|---|---|---|---|---|---|---|
| Devpost | The default global listing, with submissions and judging | Global (US) | Companies (Google, AWS, Microsoft, Meta), MLH and university events, online sponsor challenges | Yes | yes | Formerly ChallengePost (renamed 2015). [Devpost for Teams](https://itbrief.com.au/story/devpost-for-teams-streamlines-internal-hackathons-for-major-corporations) runs private hackathons (2024) |
| MLH | The official student hackathon league; Global Hack Week | North America, Europe, APAC including India | University student organisers | Yes (season list) | yes | Moved from mlh.io to mlh.com. Events often take submissions on Devpost, DoraHacks or Devfolio, so dedupe |
| Devfolio | India's main student and Web3 hackathon platform (ETHIndia, ETHMumbai) | India | College clubs, Web3 ecosystems, some corporates (Google GenAI Exchange 2024) | Yes | yes | Active |
| Unstop | Competitions plus corporate hiring challenges (Flipkart GRiD, Amazon ML Challenge), quizzes, case competitions | India (expanding to the Middle East) | Corporates hiring, colleges and fests | Yes | yes | Formerly Dare2Compete, [rebranded April 2022](https://unstop.com/blog/dare2compete-is-now-unstop/amp); [acquired PerspectAI](https://unstop.com/blog/unstop-acquires-perspectai) in September 2026 |
| HackerEarth | Hackathons and hiring challenges; sells hackathon software to companies | India and US | Corporates, banks | Yes (challenges page) | yes | Active |
| Hack2skill | Large programmes backed by corporates or government | India | Google ([GenAI Exchange](https://blog.hack2skill.com/gen-ai-exchange-hackathon-finale): about 2.7 lakh developers in 2025), MeitY Startup Hub, state governments | Yes | yes | Active |
| HackerRank | Assessment platform that hosts hiring hackathons (e.g. Meesho ScriptedBy{Her}) | Global and India | Companies | Partly | yes | OA-style; classify as `hiring_challenge` |
| TechGig | Code Gladiators and sponsored hackathons | India | Corporates; owned by Times Internet | Yes | — | Gap |
| Kaggle | Data-science competitions | Global | Companies, researchers | Yes | yes | Owned by Google |
| Zindi | AI and data competitions | Africa and global | NGOs, governments, companies | Yes | yes | Now at zindi.world |
| DrivenData | Social-impact data competitions | Global | NGOs, government agencies | Yes | yes | |
| AIcrowd | Research AI challenges | Global (Switzerland) | Universities, conferences | Yes | — | Gap |
| MachineHack, Analytics Vidhya | Data-science hackathons | India | Corporates | Yes | — | Gap |
| GeeksforGeeks, CodeChef, Codeforces, LeetCode | DSA coding contests, occasional hackathons | India and global | Companies, colleges | Yes | — | Use `coding_contest` if included |
| Hackster.io | Hardware and IoT contests | Global | Chip and hardware vendors | Yes | — | Owned by Avnet; fills the "hardware" ask |
| Topcoder | Crowdsourced development and design challenges | Global | Enterprises | Yes | — | Owned by Wipro |
| lablab.ai | Online AI hackathons built on sponsors' tech | Global | AI companies | Yes | yes | |
| Hack Club | Curated high-school hackathon directory | US and global | High-school organisers | Yes | yes | |
| Luma | RSVP pages for in-person AI hackathons (SF, Bengaluru and more) | Global | Startups, VCs, communities | Yes (Discover, calendars) | yes | Moved from lu.ma to luma.com |
| GDG (gdg.community.dev) | Chapter events and Solution Challenge | Global and India | Google Developer Groups, GDG on Campus (formerly GDSC) | Yes | yes | |
| Commudle | Indian developer-community events (CDN Hack Days) | India | Communities, GDGs | Yes | — | Gap |
| KonfHub | Ticketing for tech events and hackathons | India | Communities, companies | Yes | — | Gap |
| Reskilll | Hackathon hosting and listing | India | Colleges, companies | Yes | — | Gap; also a competitor |
| Internshala Competitions | Lists college hackathons and SIH internal rounds | India | Colleges | Yes | — | Gap; useful for SIH internal rounds |
| Smart India Hackathon (sih.gov.in) | National government hackathon; a college internal round gates entry; SIH Junior covers classes 6–12 | India | MoE Innovation Cell, AICTE, ministries | Yes | — | Gap; deadlines were extended twice in October 2026 |
| NASA Space Apps Challenge | Global weekend hackathon every October | Global | NASA and local hosts | Yes | — | Gap |
| Junction | One of Europe's largest hackathons; runs its own JunctionApp | Finland and EU | Junction and sponsors | Yes | — | Gap |
| GovHack | Government open-data hackathon | Australia and New Zealand | Governments | Yes | — | |
| Hackathon Raptors | 72-hour global online hackathons | Online (a UK community interest company) | Community and sponsors | Yes | — | |

### Web3 ecosystems

| Platform | Known for | Region | Typical hosts | Public? | In repo | Status and notes |
|---|---|---|---|---|---|---|
| ETHGlobal | Ethereum hackathons, online and in cities | Global | Ethereum ecosystem sponsors | Yes | yes | |
| DoraHacks | Multi-chain hackathons, BUIDLs, grants | Global and Asia | L1 and L2 chains | Yes | yes | Some MLH events also take submissions here |
| TAIKAI | Web3 and corporate open-innovation hackathons | EU (Porto) | Chains, corporates | Yes | yes | |
| HackQuest | Web3 education plus hackathons | Global and Asia | Chains | Yes | yes | [Acquired BuidlBox](https://hackernoon.com/hackquest-acquires-buidlbox-to-accelerate-web3-developer-ecosystem-growth) in September 2025 |
| BuidlBox | Gitcoin's former hackathons and bounties | Global | Chains | Yes | — | Part of HackQuest since September 2025 |
| Akindo | WaveHack: grant-style recurring hackathons | Japan and global | Chains | Yes | yes | |
| Encode Club | Web3 and AI hackathons, bootcamps | UK and global | Chains, AI firms | Yes | yes | |
| Colosseum | Solana's official hackathons (Frontier, Breakout) and accelerator | Global; large Indian participation | Solana ecosystem | Yes | — | Gap |
| Superteam Earn | Solana bounties and grants | India and global | Solana projects | Yes | — | More bounties than hackathons |
| Gitcoin | — | — | — | — | — | **Dead for hackathons:** [hackathons and bounties handed to BuidlBox in 2023](https://support.gitcoin.co/gitcoin-knowledge-base/misc/cgrants-bounties-and-hackathons-sunsetting-faq); Grants Stack [wound down in 2025](https://www.theblock.co/post/352055/ethereum-public-goods-funding-protocol-gitcoin-winding-down-its-software-division) |

### Enterprise, internal and open-innovation software

| Platform | Known for | Region | Typical hosts | Public? | Status and notes |
|---|---|---|---|---|---|
| Devpost for Teams | Private hackathons for employees or customers | Global | Large companies | No (private) | Launched April 2024 |
| HackerEarth Hackathons | Software for internal and external hackathons | India and US | Enterprises | Mixed | |
| Hackathon.com | Listing plus managed corporate hackathons (claims 1,200–1,500+ run for 300+ clients) | France and global | Corporates | Partly | Active |
| AngelHack | Global hackathon series and developer-relations agency | Global | Tech firms, chains | Yes (events page) | Says it is combining with StackUp |
| Agorize | Open-innovation challenges and corporate hackathons | France and global | Corporates | Yes | [Acquired by Bloomflow](https://www.cbinsights.com/company/agorize) in November 2024 |
| BeMyApp | Hackathons and developer-relations programmes | France and global | Corporates | Partly | Site is live; ownership status unverified |
| Eventornado | Hackathon management software | Estonia | Universities, IEEE, corporates | Per event | |
| ChallengeRocket | AI-assisted recruiting challenges and hackathons | Poland and EU | Corporates (e.g. Samsung Poland) | Yes | Recruiting-led |
| Brightidea, HYPE, IdeaScale, Qmarkets, Planview IdeaPlace | Internal ideation and innovation suites | Global | Enterprises | No | Never public; skip for listings |

### Dead, merged or renamed

| Was | Now |
|---|---|
| ChallengePost | Devpost (2015) |
| Dare2Compete | Unstop (April 2022) |
| Skillenza (India) | [Acquired by Imarticus Learning](https://www.cbinsights.com/company/venturesity) in July 2022 (per CB Insights); skillenza.com no longer responds |
| Gitcoin hackathons and bounties | BuidlBox (2023), then HackQuest (September 2025) |
| Agorize | Bloomflow (November 2024) |
| hackathon.io | A parked domain, for sale |
| Hackalist | Archive only ("2014–2025") |
| mlh.io, zindi.africa, lu.ma | mlh.com, zindi.world, luma.com (update adapters and links) |
| GDSC | GDG on Campus |

---

## Caveats

- Keyword counts are directional. The buckets overlap, promotional posts inflate some of them, and archive comment counts can lag behind live Reddit.
- In 2025–26, r/hackathon is dominated by Indian students. The US and global view comes mainly from r/csMajors, HN and dev.to.
- The search of r/Btechtards and r/EngineeringStudents timed out, so neither is covered; r/developersIndia is partial. X/Twitter and Quora returned little usable material.
- Vendor blogs (Reskilll, HackerEarth, Hackathon.com) have a stake in hackathons; their claims are labelled as such.
- Quotes are trimmed for length, with the original spelling kept.
