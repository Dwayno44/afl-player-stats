# Founding feature brainstorm (origin document)

This is the document that started the whole testing program — a broad brainstorm of
candidate features for the AFL disposals / fantasy model, grouped by likely value.
Every experiment in [TESTS.md](TESTS.md) traces back to an idea here. It is
preserved verbatim-in-substance as the origin reference; the combined-model test
(`exp_joint.py`) is the direct answer to its §17 (interaction effects) and §18
(use a LightGBM/XGBoost ensemble to capture them).

The model already covered a strong base: rolling form over multiple windows, season
averages, and opponent head-to-head. The brainstorm proposed the next layers:

## 1. Player role & usage
- **Centre-bounce attendance (CBA%)** — last 3 / last 5 / season, change vs season,
  and CBA% when specific teammates are absent. Rated among the highest-value adds.
- **Time on ground (TOG%)** — last 3/5/10, season, volatility, TOG by game margin,
  TOG after injury return. Project fantasy per 100 min × expected TOG.
- **Position / role classification** — don't trust listed position; label inside-mid,
  outside/wing, half-back distributor, key/intercept defender, half-forward, small
  forward, ruck, key forward. Engineer a role-change flag.
- **Kick-in involvement** — kick-ins per game, play-on %, share of team kick-ins,
  kick-in share with/without specific teammates; opponent behinds conceded.
- **Ruck role / ruck-share** — ruck contests attended, solo vs split, opponent
  hitouts & ruck fantasy conceded, hitout-to-advantage, post-contest ground ball.

## 2. Team possession environment
- Team disposals per game (L3/5/10, season, wins vs losses, differential).
- Team time-in-possession; expected possession share = team TIP − opp TIP allowed.
- Team mark rate / uncontested marks; kick-to-handball ratio.
- Team pace / tempo (total disposals, marks, tackles, inside-50s, stoppages);
  match environment rating = sum of both teams' disposals for & against.

## 3. Opponent matchup
- **Disposals conceded by role** (inside mids, wings, half-backs; fantasy to rucks;
  marks to defenders; tackles to mids/fwds) — more stable than raw H2H.
- Opponent pressure rating (tackles, pressure acts, contested-poss diff, clearance
  diff, turnovers forced).
- **Tagging tendencies** — team uses a tagger y/n, historical tagged-player
  reduction, tagger selected (late news), player tag-susceptibility → tag-risk 0–1.
- Opponent kick-in & scoring profile (behinds, inside-50s, scoring shots, accuracy).

## 4. Selection, injury & teammate availability
- **Teammate absences** — starting mids out, main ruck out, kick-in defender out,
  key forward out, tagger out, sub/managed risk; with/without splits (disposals,
  CBA%, fantasy).
- Team selection stability (number of changes, debutants, returning stars,
  reshuffle likelihood, emergencies/subs).
- Injury return / fitness (first game back, games since return, first-up scoring,
  injury type, consecutive games).
- **Substitute risk** — named on bench, age/role, recent sub history, coach pattern.

## 5. Venue, travel & location
- **Home vs away** (player home/away avg, team home differential, opponent away
  concession, interstate-travel flag).
- **Ground dimensions** — width, length, size category; player & team history at venue.
- **Travel distance & days away** — interstate y/n, distance, consecutive travel,
  return from Perth/Brisbane/Adelaide, home-state vs neutral venue.
- **Roof / indoor** — roof flag, indoor vs outdoor, dry guaranteed, wind exposure.

## 6. Weather & conditions
- Rain probability & amount, wind speed, temperature, humidity/dew, ground
  condition, roof open/closed. Effects largest on marks, kicks, goals, tackles
  (wet) and fantasy mix. Derived `weather_fantasy_penalty = rain + wind − roof`.

## 7. Time & scheduling
- **Time of day** — day/twilight/night, local start time, player time-slot splits,
  dew risk for night games.
- **Rest days** — days since last match, rest differential vs opponent, short/long
  break, 5-day break, consecutive short breaks.
- Fixture congestion & season timing (round number, pre/post-bye, finals race,
  dead rubber, Gather Round/neutral).

## 8. Game context / expected script
- Betting-market expectations (line/spread, total, implied score, win prob, line
  movement, prop line movement).
- Expected margin (close game vs blowout, leading/trailing style, junk-time).
- Ladder position & motivation (finals contention, top-four race, eliminated,
  rivalry, milestone).

## 9. Match style & phase-of-play
- Clearance & stoppage environment (team/opp clearances, centre vs stoppage, total
  stoppages, ball-ups).
- Contested vs uncontested possession profile (player & opponent rates).
- Zone usage (defensive-half / midfield / forward-half disposals & concessions).
- Scoring source split (stoppage / transition / kick-in / tackle / scoring fantasy).

## 10. Player statistical profile
- Variance & consistency (std L5/10/season, coefficient of variation, median,
  quartiles, hit-rate over line, ceiling/floor games).
- Distribution skew (skewness, blowout sensitivity, injury/sub-cleaned, outlier
  flags) — test negative-binomial / Poisson-lognormal / quantile vs Normal.
- Per-minute production (disposals/kicks/marks/tackles per 100 min) →
  expected = rate × expected minutes.

## 11. Fantasy-component features
- Project the components (kicks, handballs, marks, tackles, hitouts, goals,
  behinds, frees) and sum to fantasy, rather than projecting fantasy directly.

## 12. Market & line-specific
- Line level (offered line, distance from mean, historical hit-rate at line,
  alt-line ladder shape, overround, price movement, time since open).
- Stale-price & liquidity (time since update, number of books, spread, Betfair
  liquidity, line move after team news) → output a market-quality/actionability score.

## 13. Data cleaning & exclusions
- Subbed/injured-game handling (subbed in/out, in-game injury, very low TOG) → keep
  raw / full-game / non-sub / TOG-adjusted averages.
- Automated role-change detector (CBA% jump, kick-in-share jump, TOG jump, heatmap
  shift, disposal-zone change, teammate absence) → upweight recent games.

## 14. Suggested high-priority feature set (the brainstorm's ranking)
1 Expected role / CBA / position · 2 TOG & per-minute · 3 Team possession
environment · 4 Opponent concessions by role · 5 Team selection / teammate absences
· 6 Kick-ins & ruck share · 7 Venue/travel/rest · 8 Weather/roof/dew · 9 Expected
game script from line · 10 Market movement / stale-line indicators.

## 15–16. Per-target feature sets
Distinct feature lists for **disposals** (form, role, TOG, team env, opponent,
venue, game script, selection, weather, distribution) and **fantasy** (components,
scoring mix, role, team style, opponent fantasy-by-role, weather, venue, script,
volatility, selection). Headline engineered features:
`expected_disposals = per100 × expTOG × team_poss_adj × role_adj × opp_role_adj`;
`expected_fantasy = Σ projected components × point weights`.

## 17. Interaction effects worth testing  ← *the core hypothesis this test answers*
Signals that may be weak alone but powerful in combination:
- CBA% × opponent clearance weakness
- kick-in share × opponent behinds
- rain × tackle rate
- roof × mark-heavy team
- wide ground × wing role
- teammate-mid-out × player CBA history
- heavy favourite × defender role; heavy underdog × key-defender/interceptor
- short break × older player
- tagger selected × star-mid usage

> "These interaction terms are especially useful in tree-based models such as
> LightGBM/XGBoost."

## 18. Model-structure upgrades
Role-adjusted averages · per-minute modelling · negative-binomial / Poisson-lognormal
for counts · quantile regression for intervals · component fantasy modelling ·
hierarchical player/team model · recency decay · Bayesian shrinkage · **ensemble
(stable baseline + ML context adjustments)**.

## 19. Backtesting discipline
Add features incrementally, measure MAE/RMSE/calibration/Brier each step; **use
walk-forward validation by round, never a random split.**

## 20. The brainstorm's own ranking of the user's hunches
Team time-in-possession **High** · location/home-away/travel **Medium** · team
win-record/form **Medium** (convert to expected script) · time of day **Low-medium**
· team form **Medium** (use style/possession sub-features, not win-loss). "Role +
TOG + team-possession environment + opponent role concessions" expected to beat
broad variables like time of day or raw win-loss.
