# Handoff — Punters Mate: test register complete, fantasy shadow-model pending

Date: 2026-06-09 · Repo: `C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats`
(github.com/Dwayno44/afl-player-stats, branch `main`, Pages site
dwayno44.github.io/afl-player-stats/). User in Perth (AWST, UTC+8).

## Read these first (don't re-derive — they're committed)
- `HANDOVER.md` — base app, data sources, build steps (source of truth for the app).
- `MODEL.md` — technical model + every backtest, incl. §7 honest product position.
- **`TESTS.md`** — the **test register**: every signal tried + verdict. Read before
  proposing any "new" feature; almost everything has been tested.
- `BRAINSTORM.md` — the founding feature wishlist all testing traces back to.
- `explainers/` — plain-language `what-it-is` / `what-we-tested` / `live-results`.
- Memory: `project_punters_mate.md`, `punters-mate-feature-backtests.md` (user auto-memory).
- Recent commits: `72560c2` (test register + experiments), `6ac3b03` (R13 scorecard +
  self-updating page), `e8d9e07` (automation + product position), `b9d8d20` (explainers).

## The state in one paragraph
This session was an honest reckoning, not feature-building. Conclusion (now on the
record): a public-box-score model **cannot beat the Sportsbet disposal market** —
the value tints are negatively correlated with outcome (adverse selection), and
every brainstormed lever (TOG, CBA, concession team/role/**line**, game-script,
teammate-absences, venue/travel/scheduling) tested individually AND jointly is
noise/secondary for disposals. The product is reframed as an **honest guidance tool
for punters already betting**, not an edge engine. R13 graded: floor calibration
**87.5% vs 85% target** (sound); value ROI **−3.1% / 52 bets** (negative, as predicted).

**The one genuine positive in the whole program:** the combined LightGBM model
(`exp_joint.py`, answering BRAINSTORM §17/§18) beats the blend on **fantasy by
~2.6% OOS** (stable across seeds; ~1.1% non-linear form + ~1.4% real combined
context), while **disposals stay null** (+0.1%). See `TESTS.md` "Combined model".

## THE OPEN THREAD (the next task) — fantasy shadow A/B
Validate whether that −2.6% fantasy projection gain becomes a real **betting** edge
against Sportsbet's fantasy-points market, *before* putting any ML on the public
page. User said "no rush" — data is already accumulating, so pick up anytime.

Already in place:
- `scorecard.py snapshot` now captures, per player, `f_proj`/`f_sigma` (blend
  fantasy) **and `f_ladder`** (Sportsbet `od_ladder_F`) — committed; active from the
  R14 Friday snapshot. The ladders vanish once a round concludes, hence pre-game capture.
- `exp_joint.py` has the working LightGBM (native API, train 2025 → test 2026).

To build (`fantasy_lgbm.py` + a `grade` extension):
1. A reusable fantasy projector: train LightGBM on `cba_games.csv` (AFL-API data;
   refresh via `fetch_cba.py` to include the latest round) and project fantasy for the
   snapshot's upcoming players. Friction: **name-join** API↔page (page uses CSV
   `"Surname, Given"`; API gives given/surname) — reuse `lineups._norm`/`_strip_mid`.
2. Store the shadow `lgbm_f_proj` alongside `f_proj` in the snapshot (run it at
   snapshot time for a fair pre-game projection).
3. Extend `scorecard.py grade` to compute fantasy **value-pick ROI two ways — blend
   vs LightGBM** — against the captured `f_ladder` (use `Normal(proj, f_sigma)` for
   P(≥N)), and log both. Over weeks, `scorecard.py log` shows if LightGBM wins money.
- Honest expectation: tighter projection ≠ market edge (same info-asymmetry); weight
  toward "tighter but not edge", but settle it with real money-weighted results.

## Gotchas (will bite a fresh agent)
- **Bash cwd doesn't persist** between calls — `cd` into the repo each call, or use
  the absolute venv python: `C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats\.venv\Scripts\python.exe`.
- **Windows console is cp1252** — `print()` with `≥`/em-dash/`→` crashes; use ASCII.
- **afltables CSV round numbering is OFFSET** (its "R13" = AFL R12). **Grade via the
  AFL API, not the CSV** — `scorecard.py` already does this. Don't reintroduce the bug.
- AFL API works with `verify=True` (no proxy); token flow in `lineups.py`. Sportsbet
  is **AU-IP only** (odds builds must run locally, not on US GitHub runners).
- `lightgbm` 4.6.0 is installed in the venv but **deliberately NOT in
  `requirements.txt`** (experiment-only; the CI build must stay lean). Its sklearn
  wrapper needs scikit-learn — use the **native `lgb.train` API**.
- Snapshot for **un-named** games includes non-22 players (provisional); `grade`
  drops anyone without an actual — correct behaviour.
- **Parallel sessions touch this repo.** Stage files **explicitly** by name; never
  `git add -A`. Leave untracked: the monetisation handoff doc, root icon PNG/SVG,
  `score_round*.py` (superseded scratch), `env_meta.json` (gitignored cache).
- Commit convention: new commits (not amends), branch `main`, deploy Pages from
  `main`/`docs`, trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Automation (LOCAL Claude scheduled tasks, NOT GitHub Actions — run while app open)
- `afl-weekly-snapshot` — Fri 5pm AWST: build `--odds` + snapshot current round.
- `afl-weekly-grade` — Mon 12pm AWST: grade pending → `report-md` → push the
  self-updating `explainers/live-results.md`.
- `afl-r13-final-scorecard` — **disabled** (R13 done); can be deleted in the UI.
- User chose to keep these local (not migrate to GitHub Actions).

## Suggested skills
- **None required** for the build — it's direct coding/analysis.
- Run `/handoff` again if you stop mid-build.
- If asked to "run/verify the page", check `HANDOVER.md` for the `matchup_app.py
  --odds` build first.
- Consider `anthropic-skills:consolidate-memory` if the project memory files have
  drifted after several sessions.
