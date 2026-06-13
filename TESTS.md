# Test Register — every signal we've tried

The durable record of what's been tested on the projection/value model, so the
knowledge stops living only in chat logs and nobody re-walks a dead end. The
plain-language explainer ([explainers/what-we-tested.md](explainers/what-we-tested.md))
summarises this; the technical detail is in [MODEL.md](MODEL.md).

**Legend** — Verdict: ✅ confirmed by a backtest/analysis in the repo · 🟡 explored
(data available / inspected, no dedicated end-to-end backtest) · 🟠 tested in an
earlier session and **recollected as noise/secondary**, but no backtest preserved in
the repo (not independently reproducible here) · ⚠️ tested earlier, outcome unknown
— needs confirming · ➖ built into the product (not a projection edge).

All confirmed backtests are walk-forward (no peeking), 5-fold cross-validated, over
~34,000 player-games (CSV, 2022–26) or ~14,600 (AFL-API, 2025–26).

## Combined model — do the weak levers *add up*? (the interaction test)
The one test that answers "did testing levers individually miss a combined gain?"
([BRAINSTORM.md](BRAINSTORM.md) §17 interactions, §18 LightGBM ensemble). We threw
**every** assembled lever — form, TOG, per-minute, CBA, role (clearances/ruck/
kick-ins), opponent disposals-against, environment (home/away, day/night, venue,
round), plus the blend itself — into one gradient-boosted model and measured it
**out-of-sample** (train 2025 → test 2026, 5 seeds). `exp_joint.py`.

| Target | Verdict | Finding |
|---|:--:|---|
| **Disposals** | ✅ null | LightGBM = **+0.1%** vs the blend (3.99 vs 3.99) — combining adds nothing; the model leans almost entirely on `blend`/`L10`/`season_avg`. The box score really is tapped out for disposals. |
| **Fantasy** | ✅ **real gain** | LightGBM = **−2.6%** (17.48 vs 17.95), stable across seeds (±0.02). Ablation: **~1.1% from the tree's non-linear handling of form** (a pure linear re-weight buys ~0 — season-0.80 is identical), plus **~1.4% from genuine combined context** (opponent DA, venue, volatility, TOG each add a sliver). The whole gain needs the model; there's no cheap linear shortcut. The "levers combine" effect is real but modest, and specific to fantasy (a composite stat). |

**Takeaway:** for disposals, combining = null (the blend is essentially optimal —
even a full ML model can't beat it). For **fantasy**, a LightGBM ensemble is a real,
replicable **~2.6%** improvement (≈1.1% non-linear form + ≈1.4% combined context) —
the first thing in the whole program to beat the baseline, and it **requires the
model** (no free linear re-weight). The user's "combine the levers" hypothesis,
vindicated for fantasy. (Weather, since tested individually via Open-Meteo — null,
see Conditions — remains untested *in combination*, but its individual nulls leave
little to combine.)

## Foundational model & calibration
| Signal / choice | Verdict | Finding | Evidence |
|---|:--:|---|---|
| Season-anchored blend (season + L3/L5/L10 + H2H) | ✅ | Beats every single-window alt; re-tuning can't beat it OOS | `backtest.py` |
| Form-window selection (L3/L5/L10 vs one window) | ✅ | Multi-window doesn't beat the simple blend OOS | `backtest.py` |
| Disposal floor (vol-scaled Normal @85%) | ✅ | Holds ~85% as designed (R13 live: 87.5%) | `matchup.py`, scorecard |
| Goal floor (Poisson, decoupled @65%) | ✅ | Calibrated; goals too sparse for 75% | `matchup.py` |
| Fantasy (built from components + Normal floor) | ✅ | Component build ≈ direct, more debuggable | `matchup.py` |
| Hit-out floor (Normal) | ✅ | Mildly *conservative* — edges if anything understated | `hitouts_value.py` / calib |

## Role & usage
| Signal | Verdict | Finding | Evidence |
|---|:--:|---|---|
| Time-on-ground / per-minute | ✅ | Null as built; ~8–9% *ceiling* if minutes were known, but unreachable (priced on team news) | `exp_tog.py`, `exp_oracle.py` |
| Centre-bounce attendance (CBA) | ✅ | ~1%; redundant with minutes | `fetch_cba.py`, `exp_cba.py`, `exp_oracle.py` |
| Role classification (box-score buckets) | ✅ | Doesn't beat per-player history | `exp_concession.py` |

## Opponent & matchup
| Signal | Verdict | Finding | Evidence |
|---|:--:|---|---|
| Opponent concession (team, league-debiased) | ✅ | Can't beat the existing H2H term | `exp_concession.py` |
| Opponent concession by role | ✅ | *Worse* than team-level (slices too thin) | `exp_concession.py` |
| Disposals-against recent trend (team total) | ✅ | ~0% (corr +0.003) | `exp_team_da.py` |
| Disposals-against **by line** (back/mid/fwd) as a selection tilt | ✅ | Teams have **no persistent** concede-to-line trait (lag-1 autocorr ±0.04 ≈ noise), so it can't be a stable pick signal. Residual corr +0.033; softest-line bucket cleared floors 88.1% vs 85.2% toughest — a faint lean, not an edge. *(Run 2026-06-12; the 72560c2 commit message pre-stated this verdict before the run — verified correct.)* | `exp_line_da.py` |
| Disposals-against **by line** (back/mid/fwd) — incl. as a *selection* tilt, not just projection | ✅ | Noise. Concede-to-line **doesn't persist** round-to-round (lag-1 autocorr +0.04/−0.04/+0.00), residual corr +0.03, and the softest-line bucket clears only ~3pts more than the toughest *non-monotonically*. Concession doesn't concentrate persistently by line. | `exp_line_da.py` |
| Pressure / contest stats (pressure acts, contested rate, hitout-to-adv) | 🟡 | Pulled from official feed; no signal beyond form in the oracle decomposition | `fetch_cba.py`, `exp_oracle.py` |

## Team & game context
| Signal | Verdict | Finding | Evidence |
|---|:--:|---|---|
| Game script / expected margin | ✅ | ~1% even at the perfect-margin ceiling | `exp_gamescript.py` |
| Teammate absences (with/without splits) | ✅ | Actively *harmful* (+13% MAE where it fires) | `exp_absence.py` |

## Venue, travel & scheduling  *(earlier sessions; outcomes from recollection)*
Blanket recollection: all tested individually, each found **noise or secondary**.
| Signal | Verdict | Finding | Evidence |
|---|:--:|---|---|
| Home vs away | 🟠 | noise/secondary | `venues.py`, commit c263e09 |
| **Home state vs away state** — incl. a team at a *different venue in its own state* (e.g. a Victorian side at another Vic ground: MCG↔Marvel↔regional) — distinct from interstate travel | 🟠 | noise/secondary | `venues.py` |
| Interstate travel (out-of-state trip) | 🟠 | noise/secondary | — |
| Ground dimensions (size/width) | 🟠 | noise/secondary | — |
| Time of day (day/twilight/night, dew) | 🟠 | noise/secondary — Codex handoff: MCG day games ~neutral-to-suppressive | Codex disposals-against handoff |
| Rest / short breaks / pre-post bye | 🟠 | noise/secondary | — |
| Venue/home-state enrichment (built into model) | ➖ | Enriched by joining on opponent not round | commit c263e09 |

> Note: the **combined-model test** (`exp_joint.py`, above) re-tested the whole
> environment family *jointly* — home/away, day/night, venue, round — inside the
> LightGBM, and they added nothing for disposals and only a sliver (within the
> ~1.4% context bundle) for fantasy. So "noise/secondary individually" holds up
> **even in combination**.

## Conditions
| Signal | Verdict | Finding |
|---|:--:|---|
| **Weather** — in-game rain, prior-6h rain, wind, temperature (Open-Meteo archive, 1,934 games 2022–26, 96% coverage) | ✅ | **Null for projections.** The mechanism is real at league level — wet (2mm+) games cut team marks ~12% (92.6 → 81.7) — but total disposals barely move (358.1 dry vs 357.8 wet), and at player level every weather term has residual corr ≤ +0.011 and OOS gain +0.0% for disposals *and* fantasy (wet games are only ~3.5% of the sample; ~1.5 fantasy pts/player effect vs σ≈22 is undetectable). `exp_weather.py`; hourly per-venue cache in `weather_cache/`. |
| Umpire / free-kick tendencies | ⚠️ | _to confirm — tested?_ |

## The betting side
| Test | Verdict | Finding | Evidence |
|---|:--:|---|---|
| **Market line as a projection INPUT** (blend toward the Sportsbet ladder's implied median) | ✅ | The first *disposal* MAE gain in the program: on R13 (294 priced players, ladders from git history) a 50/50 blend of our projection + vig-adjusted market median beat both alone — **3.40 vs our 3.47 (−2.1%)**. Market alone does *not* beat us (3.57; raw vig-inflated 3.86). One round — snapshots now capture `d_ladder` so this validates forward each week. Tension to manage: market-anchored floors shrink the value tints toward zero by construction. | `exp_market.py` |
| **Line DRIFT — "who does late money come for?"** (change in the ladder, not its level) | 🟡 | Pilot (R13, 80 players priced in two builds 2 days apart, only 15 movers): drift direction is **real bias information** — players the market drifted *away* from underperformed the early line by −1.11 and the late line absorbed it (−0.08); corr(drift, actual−early) +0.24 among movers. But the late median did **not** beat the early on MAE in this tiny sample — drift corrected *bias*, not point accuracy. Forward capture now running (`odds_log.jsonl`: timestamped ladders per player; first 211 logged R14) — revisit at n≈300+ movers. Live use already validated qualitatively: R14 late money moved *away* from Archie Roberts, our biggest (most suspect) edge — the Hardwick fade signal in real time. | `exp_drift.py` |
| Disposal value tinting vs Sportsbet ladder | ➖ | Built into the page | `sportsbet_odds.py`, `matchup_app.py` |
| Goals / fantasy / hit-out value ladders | ➖ | Built | `matchup_app.py`, `hitouts_value.py` |
| Line drift / stale prices | ✅ | Biggest "edges" are worst bets (Hardwick $1.67→$1.90) | live analysis |
| Cash-out vs let-it-run | ✅ | Per-leg live model vs cash-out offer | `cashout.py` |
| Singles vs multis | ✅ | Stacking multiplies the margin: −3% → −10% → −18% (1/3/5-leg) | `sim.py` |
| Forum/news sentiment + availability flag | ➖ | Built into value picks | `forum_sentiment.py` |

## Live forward-validation
| What | Verdict | Finding | Evidence |
|---|:--:|---|---|
| Weekly scorecard (snapshot → grade vs AFL API) | ✅ | R13: floor 87.5% vs 85% target; value ROI −3.1% / 52 bets | `scorecard.py`, `scorecard_log.csv` |

---

### ⚠️ Rows needing your input
The **Venue/travel/scheduling** and **Conditions** rows were tested in earlier
sessions that left no written record. Give me the one-line outcome for each (and add
any signal still missing) and I'll fill them in — then this register is complete and
the explainer can cite it in full.
