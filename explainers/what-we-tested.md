# The search for an edge: what we tried, and what we found

The algorithm at the heart of this tool is simple. That's not laziness — it's where
the evidence pushed us. We tested a long list of "smarter" ideas, the kind every
footy analyst will tell you matter, and measured each one properly. Almost none of
them made the projections better. This is the story of that search, in plain terms.

## How we test an idea (without fooling ourselves)

For every idea, we replayed thousands of past games and asked: *if we'd used this,
would our projection have been closer to what actually happened?* Crucially, we only
ever let the model use information it would genuinely have had **before** each game —
no peeking at the result. That's the difference between a real test and a story you
tell yourself. We measured the average miss, in disposals, with and without the new
idea. If it didn't shrink the miss, it didn't make the cut.

## The simple core (what's actually in the model)

We anchor on a player's **season average**, then nudge it with their **recent form**
(last 3, 5 and 10 games) and their **history against this opponent**. Then we
subtract a safety margin sized to how erratic the player is, to get the conservative
**floor**. On a typical player our projection lands within about four disposals of
the real number — and, reassuringly, the floor holds about 85% of the time, exactly
as designed.

That's the whole engine. Everything below is something we *added* to it, tested, and
mostly removed.

## The ideas we tested — and what happened

**Time on the ground.** Obviously a player who's on for 90% of the game gets more of
the ball than one on for 60%. So we tried building the projection from a per-minute
rate times expected minutes. The catch: we can't predict a player's minutes any
better than their own recent average already implies. The big swings — a player
subbed out, or capped on return from injury — come from late team news, which the
betting market prices the *instant* the team is named. We proved the upside was real
(knowing the true minutes in advance would help a lot) but **unreachable** in
practice. No usable gain.

**Who they're playing.** Does the opponent matter? For disposals, less than you'd
think — a ball-magnet midfielder racks them up against anyone. We built detailed
"how much does this team concede to players like this" measures. They couldn't beat
the simple opponent-history term already in the model. (Curiously, the more
sophisticated, role-by-role version was *worse* — it sliced the data too thin.) We
also tested the popular "this defence has been leaking lately" angle — a team's
recent **disposals-against trend** — and it came back at *zero*.

> **A worked example — "Collingwood concedes the most disposals."**
> Here's a real one. Before a Round 13 game, a separate piece of research built a
> table of how many disposals each team gives up and flagged Collingwood as the
> league's softest (~394 a game) and Melbourne fourth-softest — so, "back disposal
> overs on their opponents." We checked that table against our own data and it was
> spot-on: the *fact* is true and cross-confirmed.
>
> So is it a good betting signal? Two honest answers. As **context**, yes — it
> correctly tells you this is a high-disposal game. As an **edge**, no: we
> backtested this exact signal and it's worth about **0.1%** to our projections,
> and the "trending leaky lately" part backtested at literally **zero**. And the
> market already knows Collingwood is soft — it's baked into the price, so the overs
> are *shorter*, not generous. Great orientation; not a money-maker.
>
> That gap — a real, true fact that still isn't an edge because everyone already
> knows it — is the whole story of this page in miniature.

**Teammates missing.** When a gun midfielder is out, surely his teammate inherits the
ball? Sometimes — but it's so unpredictable, player to player, that adjusting for it
made the projections *worse*, not better. As often as not, the team just plays worse,
or the opposition tags the man who's left.

**Blowouts and favourites.** Players on winning teams score a little more. But the
effect is tiny, and you'd need to know the result in advance to use it. Not worth it.

**The "holy grail": centre bounces.** If you ask any analyst for the one stat that
predicts a midfielder's output, they'll say **centre-bounce attendance** — how often
he starts at the middle. We went and pulled it straight from the official stats feed.
It moved the needle by about **1%** — because it mostly tells us the same thing the
player's recent disposals already do. The feature everyone swears by was, for our
purposes, almost redundant.

## The deeper reason nothing worked

Here's the uncomfortable truth that ties it all together. Our model only knows
**public, after-the-fact statistics**. The betting market knows all of that **plus**
things we don't: late fitness tests, role plans, tagging match-ups, and where the
money's going. We are, by definition, working with *less* information than the price
we're trying to beat. You can't reliably out-guess someone who can see everything you
can see, and more.

This shows up in the most counter-intuitive way: **our biggest "edges" are usually
our worst bets.** When our numbers scream that a price is way too generous, it's
rarely because we've found a steal — it's because the market has moved on information
we're missing.

> **A real example.** One weekend the model flagged a defender as strong value at
> $1.67. By game time the price had drifted out to $1.90 — the market had absorbed
> news that a teammate was out, pushing our man into an unfamiliar forward role. He
> barely touched it. We were holding a stale price and calling it value. The drift
> *was* the information; we just didn't have it.

## So why keep it simple?

Because we tested the alternatives and they didn't pay. A simple, honest model that
knows its limits beats a complicated one that pretends to an edge it doesn't have.
The value in this tool isn't a secret formula — it's the **honest calibration** (the
floor really does hold ~85% of the time) and the **tidy summary** of form, role and
team news in one place.

## We're still checking — in public

We don't expect you to take any of this on faith. Every round, the tool now records
its own "value" picks *before* the games and grades them *after*, automatically. Over
a month or so that builds into a real, honest scorecard of whether the value tints
actually beat the market. Our prediction, based on everything above, is that they
**won't** — and we'd rather show you that than hide it. The running results live in
[live-results.md](live-results.md).

---

*Want the technical version, with the actual numbers and methods? See
[`../MODEL.md`](../MODEL.md).*
