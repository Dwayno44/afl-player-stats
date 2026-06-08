# What this model is — and what it isn't

## In one minute

For every player in an upcoming AFL game, the tool gives you two numbers:

- a **projection** — our best estimate of how many disposals (or fantasy points)
  they'll get, and
- a **floor** — a deliberately conservative "minimum" we'd expect them to clear
  about 85% of the time.

When a game is close enough that the bookies have posted player markets, it also
lines our floor up against the Sportsbet price and tints it green or amber if the
price looks generous against our numbers. Alongside that, each pick can carry a
**team-news / chatter flag** — a quick read of injury, selection and role news from
public sources, so a late change doesn't blindside you.

That's it. It's a clean, one-screen summary of the things a punter usually has ten
tabs open to check.

## What it **is**

- **A research shortcut.** Form, season output, recent role, opponent history, team
  news and forum sentiment — gathered and laid out in one place.
- **A "how safe is this leg?" gauge.** The floor is the useful bit: a calibrated,
  conservative minimum. If you're building a multi and want legs that are likely to
  land, the floor is a sensible sanity check.
- **Honest about uncertainty.** Volatile players get a lower floor automatically.
  Players returning from injury or with thin form are flagged, not hidden.
- **Built for someone who's betting anyway.** Its job is to make the bet you were
  going to place a slightly better-informed one — not to talk you into more bets.

## What it is **not**

- **It is not a system for beating the bookies.** We've tested this directly (see
  [what-we-tested.md](what-we-tested.md)), and the honest answer is that a model
  built on public stats cannot reliably out-predict a sharp betting market. The
  market already knows everything our model knows — and more (late mail, money,
  inside role information).
- **The green "value" tints are not promised profits.** They flag where *our*
  numbers disagree with the price. Sometimes that's genuine; often it just means the
  market knows something we don't. In fact, our biggest apparent "edges" have tended
  to be our *worst* bets — because an outsized edge usually means we're missing
  information, not that we've found a steal.
- **It is not a money-making scheme.** Nobody should subscribe expecting a profit
  engine. Over time, betting against the published price is, at best, break-even
  before the bookmaker's margin.
- **It is not a tipping service.** It doesn't tell you what to back. It gives you
  inputs; the decision stays yours.

## How to use it sensibly

1. **Start from a bet you already wanted to make.** Use the floor to judge how safe
   the leg is, not to go hunting for new ones.
2. **Treat a bright-green "value" tint with suspicion, not excitement.** If the
   price looks too good, check the team-news flag — the market may have moved for a
   reason.
3. **Lean on the boring picks.** A steady player with a comfortable floor is more
   useful for a multi than a volatile one the model happens to love this week.
4. **Don't chase the model.** It's an input, not an oracle.

## The honest bottom line

The maths under the hood is simple on purpose — we tried the clever stuff and it
didn't help (that's the whole next document). What you're getting is a well-made,
honestly-calibrated **summary and sanity-check** for AFL player bets. Useful?
Genuinely, if you were betting anyway. A licence to print money? No — and anyone
who tells you their footy model is, is selling something.

---

*Gamble responsibly. Nothing here is a tip, a guarantee, or financial advice. If
betting stops being fun, call Gambling Help on 1800 858 858 (Australia).*
