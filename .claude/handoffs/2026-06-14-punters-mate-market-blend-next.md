# Handoff — Punters Mate: market-blend is the next build; R14 finishing

Date: 2026-06-14 (Sun, R14 weekend) · Repo:
`C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats` (github.com/Dwayno44/afl-player-stats,
`main`, Pages → dwayno44.github.io/afl-player-stats/). User in Perth (AWST).

## Read first
- Prior handoffs (full context, don't duplicate): `.claude/handoffs/2026-06-09-…` (the
  strategic conclusion + fantasy-shadow spec) and `…/2026-06-11-…` (R14 ops, gotchas).
- `TESTS.md` — the test register (read before proposing any feature; nearly everything's tested).
- `MODEL.md`, `BRAINSTORM.md`, `explainers/`.

## What changed since 2026-06-11 (this session)
New experiments + findings, all committed and in `TESTS.md`:
- **Market line as a projection INPUT** (`exp_market.py`) — **the headline.** Blending our
  disposal projection 50/50 with the Sportsbet ladder's vig-adjusted implied median beats
  our blend alone: **−2.1% on R13, replicated −2.2% on R14** (two rounds, both positive).
  The only *disposal* accuracy gain found, and now replicated. Snapshots capture `d_ladder`
  so it keeps validating forward.
- **Weather** (`exp_weather.py`, Open-Meteo, 1,934 games) — null for projections; the last
  untested brainstorm family, now closed. (Real at league level: wet kills marks ~12%, but
  disposals barely move; player-level +0.0% OOS.) Cache in `weather_cache/` (gitignored).
- **Line drift** (`exp_drift.py`) — "who does late money come for": carries *bias* info
  (drift-away players underperform) but sample too thin (15 movers); forward capture started
  in `odds_log.jsonl` (gitignored). `exp_drift.py log` appends ladders; revisit at ~300 movers.
- **Line-level disposals-against** (`exp_line_da.py`) — null; concede-to-line has no
  round-to-round persistence (autocorr ~0.04).
- **Page: green-only warning banner** (`matchup_app.py` `.headsup`) — live. Steers users off
  green-only (greens = biggest model edge but historically *least* reliable: ~67% floor-hit
  vs amber ~87% — adverse selection) toward amber / amber+un-highlighted. User approved the tone.
- **Live-game grading bug fixed** (`scorecard.py api_actuals`): now skips non-CONCLUDED games
  (a LIVE game's partial stats were being counted as final). Protects the Monday auto-grade.

## R14 status (as of this session)
6 of 7 games concluded; **St Kilda v GWS was LIVE**. Graded the 5 priced-and-concluded games
interim (`--no-log`): floor≥10 hit **86.8% vs 85%** (calibrated); value ROI **−13.5%/29**, with
GREEN 53% << AMBER 93% (adverse selection, again — exactly what the new banner warns about).
**Monday's `afl-weekly-grade` task finalises the full 7/7** and refreshes `live-results.md`.
(The Wed Bulldogs–Adelaide opener is not in the snapshot — predates it — so it's excluded; one-off
floor read showed 96%, but Treloar was a knife-edge clear: proj 18.6/floor 10/actual 10.)

## THE NEXT BUILD (recommended, in priority order)
1. **Productionise the market-blend** — the only replicated disposal gain. Blend the page's
   disposal projection toward the Sportsbet implied median (vig-adjusted, p*≈0.60 per
   `exp_market.py`) where a ladder exists; fall back to pure blend otherwise. ~2–3% tighter
   floors. **Tension to manage (state it in the UI):** market-anchored floors shrink the
   green/amber value tints toward zero by construction — consistent with "tints aren't edge,"
   but it shifts the product toward best-honest-projection. Decide how to reconcile with the
   freshly-added green-warning banner.
2. **Fantasy LGBM shadow** (`fantasy_lgbm.py`) — the −2.6% fantasy gain; spec in 2026-06-09
   handoff. Data (fantasy ladders) accruing since R14.
3. **Minutes/sub lever** — biggest oracle ceiling (~9%), concentrated in partial-game players;
   gated on the sub-flag check ~1h before bounce + fryzigg history.

## Gotchas (plus those in prior handoffs)
- **Pull before push** — CI (`afl-stats.yml`) and the Mon grade auto-push; a plain push is
  rejected. `git pull --rebase`; the repeated `error: Please commit or stash them` is just the
  always-dirty `.claude/handoffs/2026-06-05-monetisation…md` (another session) blocking the
  no-op pull — the push still fast-forwards. Stage your files explicitly; never `git add -A`.
- **cp1252 console** — no unicode in `print()`; HTML entities are fine in page strings.
- **afltables CSV round numbering is offset** (its "R13" = AFL R12); grade actuals via the AFL
  API, never the CSV. AFL API works `verify=True`; Sportsbet is AU-IP-only (odds builds local).
- **Page is too heavy (1.9 MB) for `preview_screenshot`** — it times out; verify page changes via
  grep + `preview_console_logs` (error-filter) instead. Server config: `punters-mate-docs` (8137).
- `lightgbm` installed in venv, deliberately NOT in `requirements.txt` (use native `lgb.train`).
- Throwaways left untracked: `floor_read.py`, `score_round*.py`, root icon files.

## Suggested skills
- **None required** — next steps are direct coding (`matchup.py`/`matchup_app.py` for the
  market-blend) + CLI.
- `/handoff` again if you stop mid-build.
- `anthropic-skills:consolidate-memory` if the project memory files have drifted.
