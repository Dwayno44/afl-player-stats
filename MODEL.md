# Punters Mate — Model Development & Backtesting Record

Single record of how the projection model is built and everything that has been
backtested against it. Companion to `HANDOVER.md` (which covers the app, data
sources and deployment). Last updated 2026-06-05.

All MAE/RMSE figures are **walk-forward, leakage-free** (a held-out game is
predicted using only the player's strictly-earlier games). Two datasets appear:

- **CSV** — `games_2022_2026.csv` (afltables, 2022–26), ~34.5k held-out
  player-games. Drives the live model and the Tier-A experiments.
- **API** — `cba_games.csv` (AFL/Champion Data, 2025–26), ~11k held-out
  player-games. Adds CBA + TOG fields the CSV lacks; used for the role/minutes
  spike. Its baseline MAE differs slightly (fewer, more recent seasons).

---

## 1. The current model (what ships)

Per player, per fixtured match, the model produces a **projection** and a
**confidence floor** for disposals, goals and AFL Fantasy. Implemented in
`matchup.py`.

### 1.1 Projection — season-anchored blend

A weighted blend of recent-form windows, recency-weighted head-to-head, and the
season average. Two weight sets, picked per player by whether they have met the
opponent before:

| Term | With H2H | Without H2H |
|------|---------:|------------:|
| season average | 0.65 | 0.55 |
| L3 form | 0.15 | 0.15 |
| L5 form | 0.05 | 0.05 |
| L10 form | 0.05 | 0.25 |
| head-to-head | 0.10 | — |

- **Form windows** L3/L5/L10 are each a separately-weighted average of the
  player's last *n* current-season games.
- **Head-to-head** is recency-weighted (a 2026 meeting counts 3× a 2024 one) and
  applies only when the player has faced this opponent before.
- Weights were chosen by walk-forward grid search with 5-fold CV (see §3.1). The
  windows are collinear, so the CV assigns most "recent form" weight to L3/L10 and
  ~0 to L5; the season term anchors the projection.

### 1.2 Confidence floors

- **Disposals / Fantasy** — `floor = projection − z(conf)·σ`, where σ is the
  std of the player's recent games (last ~15, current-season-scoped) and z is the
  one-sided normal quantile. Under a normal approximation the player clears the
  floor in ≈`conf` of games. Default conf = 0.85. <3 games → flat 15% haircut.
  σ is exposed to the page so the floor can be recomputed at any confidence
  client-side. Fantasy reuses this normal floor (high-count, ~symmetric stat).
- **Goals** — modelled as `Poisson(λ = projection)`; floor = largest *k* with
  `P(X ≥ k) ≥ conf`. Goal conf = 0.65 (goals are sparse; 0.75 is too strict).

### 1.3 Fantasy derivation

AFL Fantasy is a fixed linear function of the box score, so it is **derived** from
stored components rather than scraped:
`3·kicks + 2·handballs + 3·marks + 4·tackles + 1·hitouts + 6·goals + 1·behinds +
1·freesFor − 3·freesAgainst`. (The API also exposes the official `dreamTeamPoints`
directly, used in the API-based experiments.)

---

## 2. Foundational backtest — the blend beats every single predictor

Walk-forward over the CSV. The blend is better than any standalone window or the
season average alone, for all three targets:

| Predictor | Disposals MAE | Goals MAE | Fantasy MAE |
|-----------|--------------:|----------:|------------:|
| L3 only | 4.147 | 0.532 | 18.692 |
| L5 only | 4.007 | 0.522 | 18.000 |
| L10 only | 3.925 | 0.517 | 17.598 |
| season only | 3.914 | 0.517 | 17.507 |
| **current blend** | **3.884** | **0.515** | **17.399** |
| (RMSE / bias) | 4.998 / +0.056 | 0.803 / +0.012 | 22.040 / +0.046 |

**Methodology finding:** a fully re-tuned multi-window grid optimum does **not**
beat the shipped blend out-of-sample (5-fold CV: disposals & goals marginally
*worse*, fantasy marginally better). The collinear form windows leave little room;
the season-anchored shape is already near-optimal. Bias is near-zero throughout —
the model is well-calibrated on the mean.

This is the baseline every feature experiment below must beat.

---

## 3. Backtesting methodology

- **Walk-forward, no leakage.** Each held-out game rebuilds all inputs (form
  windows, season avg, H2H) from games strictly earlier than the target. Global
  quantities (opponent concession, team line-ups, league averages) accumulate in
  chronological order so nothing from the future leaks in.
- **5-fold CV for any fitted coefficient/weight**, scored on held-out folds, so
  reported gains are out-of-sample, not in-sample curve-fit.
- **Oracle ceilings.** For features that need a value not known pre-game (true
  TOG, true margin, true CBA), an *oracle* feeds the true target-game value to
  measure the maximum recoverable error — the ceiling on what any forward signal
  could buy. A real signal realizes only a fraction.
- **Fired-subset reporting.** For features that fire on a minority of games, MAE
  is also reported on just those games, where any real effect would show even if
  washed out in the full-season average.

---

## 4. Feature experiments to date

Every entry is measured against the §2 baseline. **None has been shipped** —
all were null-to-negative, or (CBA) a gain available only behind data we don't
yet have. Shipping any would have added error.

### 4.1 Tier-A features (CSV; `exp_*.py`)

| # | Feature | Disposals | Fantasy | Verdict |
|---|---------|----------:|--------:|---------|
| 2 | TOG / per-minute (`pct_played`) | +0.2% (est.) · **−8.7% oracle** | +0.2% (est.) · **−8.1% oracle** | Rate is stable; gain locked behind a minutes signal |
| 4 | Opponent concession (team) | +0.3% | +0.2% | Can't beat existing H2H |
| 4 | Opponent concession (role) | +1.2% | +1.0% | Worse — box-score role proxy too thin |
| 4 | Drop H2H entirely | +0.5% | +0.6% | H2H earns its 0.10 weight — **keep it** |
| 5 | Teammate absence (with/without) | **+4.0%** (+13% where it fires) | +0.9% (+3% where it fires) | Per-player splits are noise — harmful |
| 9 | Game script (margin) | −0.7% **oracle ceiling** | −1.1% **oracle ceiling** | Even perfect margin barely helps; line not worth sourcing |

Notes:
- **#2** decomposing into `rate × estimated_minutes` just reconstructs the raw
  total (estimated minutes = the player's own TOG average) and adds division
  noise → null. But `rate × TRUE minutes` (oracle) cuts MAE ~8% — the per-minute
  rate is accurate; the whole prize is in *predicting minutes*.
- **#4** the concession ratio must be centered on a running league-mean or it
  inflates projections (ratio/Jensen bias). Even centered, it doesn't beat the
  thin H2H term the model already has. Role-bucketing was *worse* than team-level,
  the reverse of expectation, because a box-score role proxy slices the sample too
  thin without real role data.
- **#5** "vacated usage flows to player P" does not hold at population scale —
  when a key teammate is out the team often just plays worse, or P is tagged
  harder, as often as P inherits the role. Knowing *who* inherits needs role data.
- **#9** winners' players mildly outperform projection (corr(signed margin,
  residual) ≈ +0.11 disp / +0.14 fantasy — fantasy slightly more game-script
  sensitive), but the effect is tiny and a real betting line is a noisy estimate
  of margin, so the realizable slice of an already-small ceiling is negligible.

### 4.2 Role/minutes spike — CBA from the AFL API (`exp_cba.py`, `exp_oracle.py`)

Pulled per-game CBA + TOG from `cfs/afl/playerStats/match/{matchId}` (14.6k
player-games, 2025–26) to settle whether **CBA%** — the highest-rated feature in
the source brainstorm — is worth integrating.

**Oracle decomposition (true target-game values), API dataset:**

| Knows perfectly… | Disposals | Fantasy |
|------------------|----------:|--------:|
| true TOG (minutes) | **−8.8%** | **−8.7%** |
| true CBA (role) | −1.4% | −1.0% |
| both | −9.1% | −8.5% |

- **CBA trend** (recent vs season, the realizable pre-game version) adds **~0%**
  (residual corr +0.03): it is collinear with disposal form — when CBA rises,
  recent disposals already rose, so it carries no extra signal.
- **CBA is redundant with TOG.** Adding role on top of minutes gains nothing
  (9.1 vs 8.8). **Conclusion: do not integrate CBA — worth ~1% and subsumed.**
- **The minutes prize is concentrated and mostly identifiable:** 84% of the gain
  is in the 6.5% of games with TOG < 60% (subs / early exits); the top-25%
  TOG-deviation games hold 99.3%. Full-minute games (79% of all games) are
  already nailed by the baseline.

---

## 5. Synthesis — where the model stands

1. **The box score is tapped out.** The season-anchored blend already sits near
   the achievable floor *using afltables data*. Matchup, team-environment,
   absence and game-script features tried this session do not beat it, because the
   signal they target is either tiny or collinear with form already in the model.
2. **The one real prize (~9%) is predicting minutes**, not role. It is realized
   almost entirely by **catching the players who play a partial game** — the
   named substitute and injury-return minute caps. Random in-game injuries are the
   unpredictable remainder.
3. **Realizable lever (next build):** extend `lineups.py` to read the **sub
   designation** from the live named team, and have `matchup.py` cap the
   projection and floor for the named sub (and flagged returnees). Small change to
   existing code; attacks the largest, most predictable error bucket.
4. **Open verification:** the API does not backfill roster positions on concluded
   matches, so the sub flag can't be backtested via the roster — confirm it
   populates in a live named team on a match-week Thursday (positions appear then,
   like the `EMERG` label `lineups.py` already filters), or proxy historical subs
   by low TOG.

---

## 6. Reproducibility

| Script | Purpose |
|--------|---------|
| `backtest.py` | Foundational blend tuning (standalone predictors, grid + CV weights). `--stat disposals\|goals\|fantasy`. |
| `exp_tog.py` | #2 TOG/per-minute + oracle (CSV). |
| `exp_concession.py` | #4 opponent concession, team vs role, H2H replace/keep (CSV). |
| `exp_absence.py` | #5 teammate-absence with/without splits (CSV). |
| `exp_gamescript.py` | #9 game-script margin oracle; margin reconstructed from per-player scores (CSV). |
| `probe_cba.py` | Discovers the AFL API player-stats endpoint + CBA/TOG fields. |
| `fetch_cba.py` | Pulls per-game CBA/TOG/disposals/fantasy → `cba_games.csv` (disk-cached to `cba_cache/`). |
| `exp_cba.py` | Recent-CBA-trend test (API). |
| `exp_oracle.py` | Minutes-vs-role oracle decomposition + concentration analysis (API). |

Run from the repo with the venv: `.venv/Scripts/python.exe <script> --both`
(most experiments report disposals and fantasy together). The AFL API token flow
(`lineups.py`) works on a personal machine with `verify=True` — no proxy hacks.

These experiment scripts are **scaffolding, not part of the build**; `matchup.py`
and the shipped page are unchanged by any of the above. The TOG oracle in
`exp_oracle.py` is the **benchmark to beat** — when a minutes/sub signal is wired
in, that ~9% is the target.
