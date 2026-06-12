# Handoff — Punters Mate: R14 in flight; fantasy shadow still pending

Date: 2026-06-11 (Wed night AWST) · Repo:
`C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats` (github.com/Dwayno44/afl-player-stats,
`main`, Pages → dwayno44.github.io/afl-player-stats/). User in Perth (AWST).

## Read first
- **`.claude/handoffs/2026-06-09-punters-mate-test-register-fantasy-shadow.md`** —
  the full context (strategic conclusion, the combined-model fantasy finding, the
  fantasy-shadow build spec, all the gotchas). This doc only covers what changed since.
- `TESTS.md`, `MODEL.md`, `BRAINSTORM.md`, `explainers/` — the committed record.

## What changed this session (R14 ops)
- **R14 odds published live** (`matchup_app.py --odds` → committed/pushed; the push
  had to rebase onto the CI's Jun-9 stats-CSV refresh — see gotcha below). Six
  weekend games priced; the "no markets yet" lines in the build were **R15**.
- **R14 snapshot locked** → `predictions_2026_R14.json` (143 floor≥10, **33 value
  picks**), and it now **captures the fantasy ladders** (`f_ladder`/`f_proj`/`f_sigma`)
  for the first time — the forward fantasy-validation data has started.
- **Floor read on the one game played** (Bulldogs v Adelaide opener; recomputed
  pre-game floors from the pre-R14 CSV via `floor_read.py`, an **uncommitted one-off**):
  floor≥10 hit **96%** (25 picks, only R. Sanders narrowly missed 21→19). Caveat: it
  was a high-disposal game (bias +1.6), and **Treloar exactly cleared his floor
  (proj 18.6 / floor 10 / actual 10)** — a knife-edge clear that flatters the
  headline %. Any bet on him above 10 lost. Floor calibration is the long-run number.

## Immediate next action
- **Grade R14 after the weekend.** The 33 value picks all resolve Fri–Sun. Run
  `scorecard.py grade --round 14` (or let the Mon `afl-weekly-grade` task do it →
  it also regenerates `explainers/live-results.md` and pushes). The Bulldogs–Adelaide
  opener is **not** in the snapshot (it predated it / no odds captured), so it won't
  be in the value-pick grade — expected.

## Standing open thread (unchanged — user said "no rush")
Build `fantasy_lgbm.py` (shadow LightGBM fantasy projector) + extend `scorecard.py
grade` to A/B fantasy value-pick ROI (blend vs LightGBM) against the captured
`f_ladder`, to validate whether the **−2.6% fantasy projection gain** (`exp_joint.py`)
becomes a real betting edge. Full spec in the 2026-06-09 handoff. Data accrues from R14.

## Gotchas added this session (plus all in the 2026-06-09 doc)
- **The remote moves on its own — pull before push.** The CI `afl-stats.yml`
  auto-commits CSV refreshes and the Mon `afl-weekly-grade` task auto-pushes
  `live-results.md`. A plain `git push` will be rejected; `git pull --rebase origin
  main` then push (stash unstaged changes first — `exp_line_da.py` is currently
  dirty from a linter edit; leave it). My R14 commit touched only `docs/index.html`
  + the snapshot, so it rebased cleanly.
- afltables CSV round numbering is **offset** (its "R13" = AFL R12), so the committed
  CSV lags ~2 AFL rounds — which is *why* recomputing the R14 opener's floors from it
  is leakage-free. Always grade actuals via the **AFL API**, never the CSV.
- `floor_read.py` is a throwaway (uncommitted); delete or ignore.

## Suggested skills
- **None required** — the next steps are direct CLI/coding (`scorecard.py grade`,
  then the `fantasy_lgbm` build).
- `/handoff` again if you stop mid-build.
- `anthropic-skills:consolidate-memory` if the project memory files have drifted.
