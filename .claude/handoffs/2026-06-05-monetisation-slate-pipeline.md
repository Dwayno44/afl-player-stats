# PuntersMate — Session Handoff (updated 2026-06-05, monetisation + slate pipeline)

**Repo:** `C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats` (GitHub `Dwayno44/afl-player-stats`, live `https://dwayno44.github.io/afl-player-stats/`). Odds build (AU IP required): `.venv/Scripts/python.exe matchup_app.py --odds --out docs/index.html`.

> This session pivoted from betting-strategy analysis to **productising/monetising** the tool. We agreed a business model, built a new email/message format into code, and produced a Round-13 test slate + draft email + iMessage text. Most is committed & live; the messaging copy lives in chat + Gmail drafts (captured below).

---

## A. Monetisation concept (agreed via /grill-me — full decision tree resolved)

- **Audience:** recreational AFL punters (not data-API buyers, not pros).
- **Product:** weekly model-built email/message. **Two-beat:** a *hook* (the algorithm + a menu + one standout pick) then the *slate*.
- **The slate is a ladder by "how often you want a result"** — this replaced the old conservative/aggressive idea:
  - **Game Plays** — one same-game multi per match (up to 4 legs, balanced across teams). Opposing legs decorrelate → slip prices LONGER than fair; same-team legs correlate → SHORTER. This is the differentiator.
  - **Day Multis** — best leg per game across a day (cross-game → slip ≈ fair).
  - **Weekend Swing** — best legs across the round, one big-payout multi.
- **Free vs paid:** during testing all free; from ~Round 15, **Game Plays stay free; Day Multis + Weekend Swing become the $10/week subscriber slate**. Pricing: **$10/week** (low commitment, instant feedback). ~10 AFL rounds left in 2026, target **10–20 subs** (side income, not a business). Then revisit the parked NBA concept.
- **Distribution:** **word-of-mouth only**, via the user's punter mates + their networks. No public ads, no affiliate links (legal/ToS caution: scraping Sportsbet commercially + paid tipping services are regulated in VIC/NSW — stay informal, frame as "model output" never "tips", always include responsible-gambling note).
- **Stack (decided, mostly NOT built yet):** Beehiiv (list/segments) + Stripe ($10/wk). Domain `.com` preferred over `.com.au` for WHOIS privacy (`.com.au` registry forces some contact visibility even with Domain Guard — **keep Domain Guard on**). **Repo → private** via GitHub Pro ($4/mo) for Sportsbet-scraping discretion; switch commit identity to a product email going forward. **No ABN** (personal income, under GST threshold).
- **Brand:** rebrand deferred ~2 weeks until concept proven. `fairmulti.com` and `edgemulti.com` both available; user leaning but not committed. Current name "PuntersMate" is a placeholder.
- **Sentiment analysis** (in dev, `forum_sentiment.py`, uncommitted): user wants it as a future depth layer but won't sell it until proven — test on free subs first.

## B. New this session — CODE shipped

**`round_email.py` — new `--format slate` (now the DEFAULT), commit `60f3396`.** Builds Game Plays / Day Multis / Weekend Swing. Key functions: `_upcoming` (drops started + Monday-AWST games; `--include-monday` to keep), `game_play` (≤4 legs, 2-per-team cap, greens then ambers ≥ `FILL_MIN`=0.03), `correlation_note` (counts cross- vs same-team pairs → predicts slip LONGER/SHORTER/≈fair), `day_multis`, `weekend_swing` (best-per-game topped to 8, flags same-game pairs). Legacy 3-tier view preserved via `--format tiers`. Weekly run = `matchup_app.py --odds` → `round_email.py`.

**Page republished twice** (`8a2108d`, then fresh odds `1bfb53d`) — both `docs/index.html` only. Working tree still has uncommitted in-progress files (`matchup_app.py`, `forum_sentiment.py`, `hitouts_value.py`, icons, `site.webmanifest`, etc.) — left untouched.

## C. CRITICAL workflow rule discovered (teamsheet gate)

The model recommended Nash + Setterfield who were **dropped** — because the page was built **before Thursday team-naming**. `matchup_app.py` already filters each side to the named 22 **when teams are named** (within 9 days; flags `home_named`/`away_named`), but falls back to all-players when "not yet named". **Fix = rebuild AFTER ~Thursday 6:20pm AEST naming.** That timing IS the teamsheet gate; it's automatic, no manual cross-check. Rebuild dropped both ghosts and flipped 6/8 R13 games to NAMED (Monday Coll/Melb still pending, excluded anyway). **Bake this timing into the weekly routine.**

## D. Round-13 test artifacts (the live test round)

- **Validated slip prices** (user confirmed on Sportsbet; opposing/balanced plays all read LONGER than fair as predicted, same-team GC/Bris flat): Game Plays $3.75 / $2.80 / $2.50 / $2.50 / $2.50 / $2.50; Day Multis $2.12 (Sat) / $1.83 (Sun); Weekend Swing $11.50. Standout value: **Hardwick 13+ disp @ $1.67 (+44% model edge)** — user confirmed line is real.
- **Email draft** in Gmail (`smithdk44@gmail.com`, DRAFT-ONLY) — subject "PuntersMate — Round 13 Weekend Slate 🏉", has the validated slips + correlation story + free→paid banner + RG footer, HTML + plain-text.
- **"R13 — iMessage text" Gmail draft** — plain-text teaser + slate for phone transfer (still on the EARLIER hook wording).
- **Final iMessage copy (in chat, NOT yet synced to the Gmail draft):** a locked **hook** + a combined **full-slate message**. Distribution is **iMessage** (no markdown bold; `↳` arrows render as "L." — removed; blank lines between games are essential for readability). Settled hook line: *"I've trained an algorithm that projects players' disposals and fantasy points, then compares them to the live odds to find where the bookies are soft … Something for every appetite: a multi per game, a multi per day, or one big weekend swing. Choose your own adventure. Best value this week: Hardwick 13+ @ $1.67."* The full-slate message lists every game-play leg + the 8 Weekend Swing legs, blank-line separated, RG footer `model only · not advice · 18+ · 1800 858 858`. Phone transfer method chosen: **iCloud Notes** (icloud.com → Notes → syncs to iPhone).

## E. Market report ingested (persisted to memory)

A 15-page external strategy report (`C:\Users\megan\Downloads\AFL Player Props and Fantasy Edge Product Report.pdf`) was distilled into project memory: `…/memory/punters-mate-market-report.md` (indexed in `MEMORY.md`). Read that note for the full detail. Decision-relevant reconciliation vs this session's plan:
- **Validates:** research-tool-not-tipster framing, freemium (free board + paid weekly email), disposals+fantasy focus, curation-over-volume, RG/no-guarantee language, 18+. The report names the exact white space (AFL-specific, player-prop-first, distribution-based) the model already occupies.
- **TENSION 1 — pricing:** session chose **$10/week** (~$40/mo, ~$260/season); report's market-anchored range is **$10–20/mo or $59–89/season** → our price is ~3–4× market. Be deliberate; watch test-round price sensitivity.
- **TENSION 2 — data:** session **scrapes** Sportsbet + AFL API (fine for informal WoM test); report says **license** Champion Data (stats) + Betfair (odds) for a durable/public business. Clear upgrade path at scale: license feeds, drop the scraper. Risk is contractual/ToS, not copyright (AU facts thin: IceTV, Phone Directories).
- **NEW must-do the session hadn't flagged:** **Spam Act** is product-critical for the weekly email (consent + working unsubscribe + sender ID; ACMA fined TAB $4M in 2025) → a real reason to use a proper ESP (Beehiiv) over manual BCC the moment money changes hands.
- **Report's recommended MVP:** pre-match only, two market families (disposals ladders + fantasy lines), licensed stats, Betfair Exchange as first executable odds source, free public board + one paid weekly email, no affiliate links / no live automation / no app at launch. Anti-piracy for paid email: subscriber-specific links, watermarking, time-stamped batches, perishable content behind login.

## F. Parallel product-architecture session reconciled (2026-06-05)

A second grill-me handoff (`C:\Users\megan\Downloads\afl-freemium-product-handoff-2026-06-05.md`) covered the SAME project from a freemium/technical-architecture angle. Distilled to memory: `…/memory/punters-mate-product-architecture.md` (indexed in `MEMORY.md`). Read that note for full detail.
- **Converges (settled):** monetise the service not repo access; engine private; research-tool-not-tipster; no bookmaker refs / stake-sizing / profit language in customer copy; subscriptions, individual users; v1 = weekly human-reviewed email (not a live dashboard); free = limited CURRENT view (not stale); paid = curated shortlist + game/day/round scenario groupings + correlation + rationale; confidence tiers + stat thresholds (not exact prob/EV); human verifies live ladder price before send. **Repo already made private this morning.**
- **CONFLICT 1 — paid platform:** this slate session assumed **Beehiiv** + Stripe; the product-arch session recommends **Ghost-first** (gated members/archive/login) + Stripe (only if payment-provider approves the category). Resolve before any infra build.
- **CONFLICT 2 — The Odds API:** product-arch handoff wants to test whether it returns ladder-format `player_disposals`/`player_afl_fantasy_points`. **Already answered NO** in `project_punters_mate` memory (only ~2 discrete AFL disposal points → why we scrape Sportsbet). Real licensed-ladder path = Betfair/Sportradar/TxODDS (Section E). Don't re-litigate.
- **NEW critical eng workstream (NOT started):** current build embeds the FULL model output in `docs/index.html` browser JS (verified 2026-06-05: every row ships `D_proj,D_sigma,F_proj,F_sigma,od_ladder*`). A freemium relaunch **leaks all premium data/logic**. Required: build emits TWO artifacts — private full (never deployed) + sanitized public **allowlist** (deployed); CI leak-check on forbidden keys. Paused at "Question 34" (private full + report → private GH Actions artifacts short-retention + local archive; only sanitized public deploys; only edited report → member platform).
- **Launch gates:** human legal/compliance review + payment-provider category approval, both BEFORE paid beta; resolve the licensed-data path (don't launch paid on unauthorised Sportsbet scraping).

## Open threads / next steps
1. **Immediate (last user ask):** **sync the Gmail "R13 — iMessage text" draft to the final version** (new hook + full slate incl. Weekend Swing legs). Not yet done.
2. Build **`--format chat`** into `round_email.py` so hook + slate message auto-generate with each week's slips (repeatedly offered, user hasn't green-lit).
3. Ultimately move full-slate delivery to **email/a slate page (route "b")**; iMessage carries hook-only + link. User agreed in principle but wants the long iMessage option for now.
4. Infra when proven: Beehiiv, Stripe, domain, repo→private, commit-identity swap.
5. Parked: NBA scraper (`C:\Users\megan\OneDrive\Documents\Claude\nba-fantasy\`), sentiment layer.

## Standing constraints (unchanged — do not violate)
- Per-commit identity `-c user.name="Dwayne Smith" -c user.email="smithdk44@gmail.com"`. Co-author trailer this session used `Claude Opus 4.8`. Never touch global git config. Commit only when asked; built page goes straight to `main` (GitHub Pages publishes `/docs` from main).
- No third-party API keys in repo; no new `--insecure`/`verify=False` beyond the existing lineup/odds proxy code. Odds builds need an AU IP; CI must not rebuild the odds page.
- **Never place bets / cash out / move money** — read & analyse only. Gmail is **DRAFT-ONLY** (`create_draft`, never send). Not a licensed advisor; frame as model output + RG note.
- Verify the 1.3–1.9 MB page via DOM/JSON parse, not screenshots (they time out). Note `grep -c` on the minified DATA counts *lines* not occurrences — parse the JSON to verify.

## Suggested skills for the next session
- **`update-config`** — if the user wants the Thursday-post-naming build automated via a hook/scheduled task.
- **`code-review`** — before the next commit batch (especially when adding `--format chat`).
- **`verify`** / **`run`** — to confirm a fresh `--odds` build renders the slate (DOM checks).
- **`diagnose`** — if resuming the parked NBA `nba_scrape.py` loop.
