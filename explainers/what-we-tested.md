# The search for an edge: what we tried, and what we found

The algorithm at the heart of this tool is simple. It would be easy to assume that
means we didn't try very hard. The opposite is true: the simple model is what's
*left standing* after two weeks of deliberately trying to beat it — more than a
dozen experiments, run properly, almost all of which we then threw away because
they didn't help. This is the catalogue of that search.

## The scale of it, in numbers

- **34,000+ past player-games** replayed for every backtest, walk-forward (never
  letting the model peek at the future), with 5-fold cross-validation so a result
  has to hold *out of sample*, not just look good in hindsight.
- **A second dataset of ~15,000 player-games** pulled from the official AFL
  (Champion Data) feed, specifically to test the advanced stats the public data
  doesn't carry — centre bounces, time-on-ground, kick-ins, ruck contests,
  pressure acts and more.
- **Four separate markets** modelled and calibrated end-to-end — disposals, goals,
  AFL fantasy, and hit-outs — not just one.
- **More than a dozen candidate signals** tested as projection inputs, plus the
  betting side itself (line movement, cash-out, singles vs multis).
- Result: **almost none of it beat a season-anchored average nudged by recent
  form.** That's not a shortcut. That's the finding.

## How we test an idea (without fooling ourselves)

For every idea, we replayed thousands of past games and asked: *if we'd used this,
would our projection have been closer to what actually happened?* The model only
ever sees information it would genuinely have had **before** each game — no peeking
at results. We measure the average miss in disposals, cross-validate it, and keep
the idea only if it shrinks the miss out-of-sample. For ideas that need information
you can't know in advance (a player's actual minutes, the final margin), we also
measure the **ceiling** — how much it *could* help if you knew it perfectly — so we
can tell the difference between "useless" and "useful but unknowable."

## The simple core (what's actually in the model)

We anchor on a player's **season average**, then nudge it with **recent form**
(last 3, 5 and 10 games) and their **history against this opponent**. The exact
weights were chosen by grid-searching thousands of combinations against those
34,000 games; the season-anchored blend beat every single-window alternative, and
re-tuning it from scratch couldn't do better out-of-sample. Then we subtract a
safety margin sized to how erratic the player is, to get the conservative
**floor**. On a typical player our projection lands within about four disposals of
the real number, and the floor holds about 85% of the time, as designed. We built
and calibrated the same machinery for **goals** (modelled as a scoring-rate
distribution), **fantasy** (built up from its scoring parts), and **hit-outs**.

Everything below is something we *added* to that core, tested, and mostly removed.

## What we tested — the catalogue

### Role and usage
- **Time on the ground.** A player on for 90% of the game gets more ball than one
  on for 60%, so we tried building projections from a per-minute rate × expected
  minutes. The result: no usable gain — we can't predict minutes any better than a
  player's own recent average, and the big swings (a sub, an injury cap) come from
  late team news the market prices the instant the team is named. We proved the
  *ceiling* was worth ~8–9% if you knew the minutes — but it's unreachable.
- **Centre-bounce attendance (the "holy grail").** Every analyst's favourite stat —
  how often a player starts at the middle. We went and pulled it from the official
  feed for ~15,000 games. It moved the needle about **1%**, because it mostly
  re-states what recent disposals already tell us. The decisive test showed the
  recoverable error is about *minutes*, not *role* — and minutes already swallow
  what centre bounces add.
- **Role classification.** We built a box-score role detector (inside-mid, wing,
  half-back, key forward, ruck) to tailor projections by role. It didn't beat
  treating each player as themselves.

### Opponent and matchup
- **"How much does this team concede?"** We built detailed opponent-concession
  measures, league-adjusted to remove bias, both team-wide and broken down by the
  type of player. None beat the simple opponent-history term already in the model —
  and the fancy role-by-role version was *worse*, because it slices the data too
  thin.
- **Recent disposals-against trend.** The popular "this defence has been leaking
  lately" angle. It backtested at essentially **zero**.
- **Pressure and contest stats.** Pulled from the official feed (pressure acts,
  contested-possession rate, hit-out-to-advantage) and explored as inputs — no
  reliable signal beyond what form already carries.

### Team and game context
- **Game script / favouritism.** Players on winning teams score slightly more, but
  the effect is tiny and you'd need the result in advance — even the perfect-margin
  *ceiling* was only ~1%.
- **Teammates missing.** When a gun midfielder is out, does his teammate inherit
  the ball? Sometimes — but it's so unpredictable, player to player, that adjusting
  for it made the projections *worse*.

### Venue, travel and scheduling — the "where and when"
A whole family of signals that feel like they *should* matter, each tested in turn:
- **Home vs away.** Player-level home/away splits are mostly noise once you have
  the player's form.
- **Home state vs away state, and interstate travel.** The intuitive "travelling
  team tires" effect washes out once role and form are accounted for.
- **Ground dimensions** (wide/narrow, big/small). A plausible edge for outside
  runners — in the data, too small and too noisy to move a projection.
- **Time of day and conditions** — day / twilight / night, and dew risk. We split
  output by venue and timeslot: e.g. MCG day games came out close to
  neutral-to-*suppressive*, the opposite of the "more footy, more disposals"
  intuition. Timeslot wasn't the reason.
- **Rest and the run home** — days' break, short turnarounds, pre/post-bye. A
  secondary fatigue effect at most, not a reliable projection-mover.

The verdict across the whole family was the same: real-sounding, occasionally true
as *context*, but not an *edge* once the player's own form and role are in the model.

- **Weather.** The last family standing — untested for months purely for lack of a
  data source, until we pulled hourly rain/wind/temperature for every venue and all
  ~1,900 games from a free historical archive. The folklore is half-right: wet games
  really do kill **marks** (about 12% fewer). But total **disposals barely move** in
  the wet, and at the player level no weather measure improved a single projection —
  rain games are too rare, and the effect per player too small, to matter.

### Across four different markets
We didn't just do this for disposals. We modelled and floor-calibrated **goals**,
**AFL fantasy** and **hit-outs** as well — including a dedicated ruck/hit-out value
check against the bookmaker's hit-out lines. Same story each time: the simple,
honestly-calibrated version is the one that survives.

### The betting side itself
Testing wasn't only about projections — we stress-tested the *betting* too:
- **Line movement / stale prices.** We measured what happens when the bookie's
  price drifts after we've flagged value (it's bad — see the Hardwick example
  below).
- **Cash-out vs let-it-run** and **singles vs multis.** We simulated stacking the
  value picks into multis: it *multiplies* the bookmaker's margin — a set of picks
  that loses ~3% as singles loses ~10% as 3-leg multis and ~18% as 5-leg multis.
- **Forum and news sentiment.** We built a layer that reads public chatter for late
  injury/role news and flags availability risk on each value pick.

## The deeper reason nothing worked

Here's the uncomfortable truth that ties it all together. Our model only knows
**public, after-the-fact statistics**. The betting market knows all of that
**plus** things we don't: late fitness tests, role plans, tagging match-ups, and
where the money's going. We are, by definition, working with *less* information
than the price we're trying to beat. You can't reliably out-guess someone who can
see everything you can see, and more.

This shows up in the most counter-intuitive way: **our biggest "edges" are usually
our worst bets.** When our numbers scream that a price is way too generous, it's
rarely because we've found a steal — it's because the market has moved on
information we're missing.

> **A real example.** One weekend the model flagged a defender as strong value at
> $1.67. By game time the price had drifted out to $1.90 — the market had absorbed
> news that a teammate was out, pushing our man into an unfamiliar forward role. He
> barely touched it. We were holding a stale price and calling it value. The drift
> *was* the information; we just didn't have it.

> **A worked example — "Collingwood concedes the most disposals."**
> Before a Round 13 game, separate research flagged Collingwood as the league's
> softest disposal matchup, so "back disposal overs on their opponents." We checked
> that table against our own data and it was spot-on — the *fact* is true. So is it
> a good bet? As **context**, yes. As an **edge**, no: we backtested this exact
> signal at ~0.1%, the recent-trend part at zero, and the market already knows
> Collingwood is soft, so the overs are *shorter*, not generous. A real, true fact
> that still isn't an edge because everyone already knows it — the whole story in
> miniature.

## So why keep it simple?

Because we tested the alternatives — thoroughly, at scale — and they didn't pay. A
simple, honest model that knows its limits beats a complicated one pretending to an
edge it doesn't have. The value in this tool isn't a secret formula; it's the
**honest calibration** (the floor really does hold ~85% of the time) and the **tidy
summary** of form, role, matchup and team news in one place.

## We're still checking — in public

We don't expect you to take any of this on faith. Every round, the tool records its
own value picks *before* the games and grades them *after*, automatically, and
publishes the running scorecard. Our prediction, based on all of the above, is that
the value picks **won't** beat the market over time — and we'd rather show you that
than hide it. The live results are in [live-results.md](live-results.md).

---

*Want the technical version, with the actual numbers and methods? See
[`../MODEL.md`](../MODEL.md).*
