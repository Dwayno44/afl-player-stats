"""
Financial what-if on Round 13's value picks (the 52 amber/green disposal tints):
  1) $5 single on every player
  2) the same players combined into random 3-leg multis (each player used once)
  3) the same players combined into random 5-leg multis
Multis are random, so we Monte-Carlo the groupings. Stake is $5 per bet throughout.
Void picks (player didn't play) are excluded — in reality the stake is refunded.
"""
import json
import numpy as np
import scorecard as SC

STAKE = 5.0
SIMS = 20000
rng = np.random.default_rng(0)

snap = json.load(open('predictions_2026_R13.json', encoding='utf-8'))['rows']
actuals, played = SC.api_actuals(2026, 13)

picks = []
for r in snap:
    if r['tint'] in ('clear', 'border') and r.get('price'):
        a = actuals.get(SC._key(r['team'], r['player']))
        if a is None:
            continue                      # void / DNP -> excluded
        picks.append((float(r['price']), 1 if a >= r['floor'] else 0))

price = np.array([p for p, _ in picks])
hit = np.array([h for _, h in picks])
n = len(picks)
print(f"{n} value picks with results   (overall hit {hit.mean()*100:.1f}%, "
      f"avg price {price.mean():.2f})\n")


def singles():
    pnl = np.where(hit == 1, STAKE * (price - 1), -STAKE).sum()
    staked = n * STAKE
    return staked, pnl


def multis(k):
    """Monte-Carlo random k-leg multis, each player used once; drop the remainder."""
    m = n // k
    use = m * k
    pnls = np.empty(SIMS)
    profitable = 0
    for s in range(SIMS):
        idx = rng.permutation(n)[:use]
        pr = price[idx].reshape(m, k)
        hh = hit[idx].reshape(m, k)
        win = hh.all(axis=1)                       # multi pays only if all legs hit
        legpay = np.where(win, STAKE * pr.prod(axis=1) - STAKE, -STAKE)
        pnls[s] = legpay.sum()
        profitable += pnls[s] > 0
    staked = m * STAKE
    return staked, pnls, profitable / SIMS, m


def line(name, staked, pnl, roi, extra=""):
    print(f"  {name:<26} staked ${staked:6.0f}   net ${pnl:+7.2f}   ROI {roi:+6.1f}%{extra}")


st, pnl = singles()
print("STRATEGY 1 — $5 singles on all players")
line("singles", st, pnl, pnl / st * 100)

for k in (3, 5):
    st, pnls, pwin, m = multis(k)
    roi = pnls.mean() / st * 100
    print(f"\nSTRATEGY {2 if k==3 else 3} — random {k}-leg multis ($5 each, {m} multis, "
          f"{m*k}/{n} players used)")
    line(f"{k}-leg multi (avg)", st, pnls.mean(), roi,
         f"   profitable {pwin*100:.0f}% of the time")
    print(f"  {'':26} range  ${np.percentile(pnls,5):+.0f} (P5)  …  "
          f"${np.percentile(pnls,95):+.0f} (P95)   best ${pnls.max():+.0f}  worst ${pnls.min():+.0f}")
