# Handoff — Finish benchmarking Round 20, prepare for Round 21

**Date:** 2026-07-26 · **Repo:** `C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats` (Punters Mate, AFL disposal-floor tool)
**Live:** dwayno44.github.io/afl-player-stats/ · GitHub Pages from `main`/`docs` · user in Perth (AWST), AU IP
**Head commit:** `a6dba58` (all work below is pushed; tree clean)

Your two jobs: **(1) grade R20** into the track record, **(2) open R21** so the page is live before its opener. Details, exact commands, and the one non-obvious decision are below.

---

## Current state (verified this session)

- `current_round(2026)` = **21**. **R20 is fully CONCLUDED** (9 games, Jul 23–26). **R21 is SCHEDULED** (9 games, Jul 30 → Aug 2; opener Thu Jul 30).
- Snapshots on disk: `predictions_2026_R{17,18,19,20}.json`. R20's exists and is a **real pre-game snapshot** (built 2026-07-20) — see the nuance below.
- Live page (`docs/index.html`) currently shows an **R20 floors-only preview** (stale now that R20 is done — fixing that is job 2).
- Track record (`docs/results.html`, `explainers/live-results.md`): **7 complete rounds, running shown-floor 84.5%.** R18/R19 are labelled floors-only reconstructions (†). R20 shows as "(in progress)" with its 1 early game — grading it (job 1) finalises it.

Scorecard so far (shown-floor): R13 87.5 · R14 85.0 · R15 87.8 · R16 81.6 · R17 83.2 · R18 83.1† · R19 84.2† · **run 84.5%**.

---

## JOB 1 — Grade R20 (finish benchmarking)

R20 has a legitimate pre-game snapshot, so grade it the normal way:

```bash
cd /c/Users/megan/OneDrive/Documents/Claude/afl-player-stats
git stash -u >/dev/null 2>&1; git pull --rebase origin main; git stash pop 2>&1 | tail -1
.venv/Scripts/python.exe scorecard.py grade --round 20      # appends complete row (dedupes the partial)
.venv/Scripts/python.exe scorecard.py report-md             # -> explainers/live-results.md
.venv/Scripts/python.exe results.py                          # -> docs/results.html
```

**⚠️ The one decision you must make — R20 is floors-only but NOT "reconstructed".**
`predictions_2026_R20.json` has **0 tinted / 0 odds ladders** (Sportsbet markets weren't posted when we opened R20, and we never re-snapshotted with odds). So `value_n` will be **NaN**, and with today's code R20 will render **"—†"** and fall under the existing footnote that says *"the app was offline that week."* **That wording is wrong for R20** — the app wasn't offline; the odds simply weren't up at snapshot time / we didn't re-capture them.

Pick one before publishing:
- **(A, recommended, low effort)** Generalise the †-footnote wording in both `scorecard.py:report_md` and `results.py:build_html` to something round-cause-agnostic, e.g. *"Floor-only — live pre-game odds weren't captured for this round, so there are no value picks; the floor figures are genuine."* Covers R18/R19 **and** R20 honestly. The floor number is fully valid either way.
- **(B, more work, probably not worth it)** Try to recover R20 odds from `odds_log.jsonl` if any run logged R20 ladders, rebuild the snapshot's tints, re-grade for real value picks. Likely no R20 rows were logged — check first, don't sink time.

After deciding, regenerate both pages and commit. Expect running floor to stay ~84%.

**Why R20 floors are trustworthy despite no odds:** the floor is `proj − z·σ`, fixed by prior form before the round — identical whether or not odds exist. Only the green/amber *value* layer needs odds.

---

## JOB 2 — Open R21 (page live before Thu Jul 30 opener)

Standard "open the round": build with odds → snapshot the baseline → publish. Markets usually post ~Wed (Jul 29).

```bash
cd /c/Users/megan/OneDrive/Documents/Claude/afl-player-stats
git stash -u >/dev/null 2>&1; git pull --rebase origin main; git stash pop 2>&1 | tail -1
.venv/Scripts/python.exe matchup_app.py --odds --out docs/index.html   # floors + odds + sentiment + drift
.venv/Scripts/python.exe scorecard.py snapshot --round current          # writes predictions_2026_R21.json (BASELINE)
git add -A && git commit -m "Open R21: live odds view + baseline snapshot"
git pull --rebase origin main && git push origin main
```

- If **no R21 disposal markets yet** (build prints "no disposal markets yet" for every game): still snapshot + publish a **floors-only R21 preview** — but you'll then be recreating the R20 problem. **Better:** publish the floors preview now, and **re-run the full `--odds` build + a fresh `snapshot --round 21` once markets post** (Wed/Thu) so the baseline actually carries odds. The last `snapshot` of the round wins.
- **Thursday pre-game refresh** (before ~4pm AWST, ahead of the opener): re-run **only** `matchup_app.py --odds` (NOT snapshot) so drift is measured against the Wed baseline, then commit/push. This is exactly what the `afl-thursday-pregame-publish` scheduled task does.

### ⚠️ Root-cause to prevent recurrence
R18 and R19 dropped out of the record because the **scheduled snapshot tasks only run while the app is open, and it was closed those weeks.** Two tasks exist (`afl-weekly-snapshot` Wed 6pm AWST, `afl-thursday-pregame-publish` Thu 3:35pm AWST — see `list_scheduled_tasks`), but **do not rely on them.** Treat "open the round manually" as the norm. If a round ever gets missed again, use **`backfill_snapshot.py --round N`** (new this session) to reconstruct floors, then grade — but that can never recover value picks, so manual/live capture is always preferable. Note the Thursday task is still **unapproved** (may pause on first run for Sportsbet/git permissions — user can "Run now" once).

---

## Standing model priority (recommended, NOT yet authorised — get a yes first)

**Floor-z tweak.** The shown-floor has now landed **below 85% for four straight rounds** (R16–R19: 81.6/83.2/83.1/84.2), running 84.5%. This is no longer noise — it's the ~2.5pt shown-slate optimism identified in `exp_floor_calib.py` (`TESTS.md`, "Disposal floor" row) showing up live. The fix: nudge the floor's z (or fatten the left tail — disposal downside is heavier than Normal: tags, early subs) so the **shown slate** clears ~85% without wrecking the all-players calibration (already bang-on at 85%). Build it in an `exp_floor_z.py`, walk-forward on `games_2022_2026.csv`, before touching `matchup.py`. I offered this at end of session; **user invoked /handoff before answering, so it is unconfirmed — propose, don't just do.**

Other proven-but-shelved items (unchanged, see `TESTS.md`): productionise **market-blend** (−2% disposal MAE, replicated) and **fantasy LightGBM shadow** (−2.6%).

---

## This session's completed work (don't redo — commits below)

- `a6dba58` — Backfilled R18/R19 floors (`backfill_snapshot.py`, new); labelled reconstructed on both public pages; deduped `scorecard_log.csv`; fixed `report_md` NaN-`value_n` crash; R20 live refresh.
- `5da9d9d` — **FNFGainz / position-type DvP test → NULL** (`exp_position_da.py`). Inside/outside-mid split via CBA; the 4th and final granularity of opponent-concession to die. No position type's concession persists round-to-round (autocorr ≈ 0). Uncontested-ball-conceded is the only mildly-persistent team trait (+0.14) but yields no usable tilt. Written up in `TESTS.md` + `explainers/what-we-tested.md`. *(This closes the "what remains high-priority to test" question: little does — the register is near-complete; remaining upside is productionising known gains + the floor-z fix, not new signals.)*
- Earlier this session: graded R16 & R17; rolled live page R16→R17→R20; **rescheduled the weekly tasks to Wed+Thu** (from Fri) and made them publish.

---

## Gotchas (environment)

- **cwd resets between Bash calls** → always `cd /c/Users/megan/OneDrive/Documents/Claude/afl-player-stats` first.
- **Always `git pull --rebase` before push** — CI (`Auto-refresh stats CSV`) and other sessions push to `main`; a handoff/other dirty file can block a no-op pull (stash/pop pattern above).
- **Console is cp1252** — don't print unicode from Python to stdout (use HTML entities in files; ASCII in prints).
- **`index.html` is ~2MB** — `preview_screenshot` times out on it; verify via `grep`/`read_page` on the light `results.html` instead.
- **Data feeds are time-inconsistent in this sandbox.** The AFL API (source of truth for results) can run *ahead* of the system clock and of Sportsbet/Squiggle (which lag). When rounds don't line up, **trust the AFL API for what's concluded**; confirm with the user if a publish decision hinges on it (this bit us around R16). `current_round` and `fixtures.get_fixtures(remaining_only=True)` both key off it.
- **Snapshots capture the whole remaining fixture on the page** (600+ rows), not one round; `grade`/`results.py` filter to the round's concluded games via the API. Normal.

## Reference artifacts (read, don't duplicate)
- `TESTS.md` — full signal register (position-DvP row is new). `MODEL.md` — model detail. `explainers/what-we-tested.md` — plain-language.
- `scorecard.py` (snapshot/grade/report-md), `results.py` (results.html), `backfill_snapshot.py` (missed-round recovery), `matchup_app.py` (`--odds` build), `exp_position_da.py` (this session's null test).
- `scorecard_log.csv` — per-round history (value ROI kept here internally; dropped from all public pages per user).

## Suggested skills
- **`afl-player-stats:handoff`** — to write the next handoff when this is done.
- **`afl-player-stats` repo scripts** above are the toolkit; no external skill needed for jobs 1–2.
- If you take on the floor-z work after user approval, there is no dedicated skill — follow the `exp_*.py` pattern (walk-forward, leak-free, 5-fold) established in the repo.
