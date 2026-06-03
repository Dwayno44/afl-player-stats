"""
Cross-stat consistency comparison for betting.

For each stat, walk-forward predict with the live season-anchored blend and report
relative error = MAE / mean(actual) -- the betting-relevant accuracy, since a
floor is proj - z*sigma and what matters is error *as a fraction of the line*.

Two cohorts:
  ALL      : every held-out game (includes low-volume players you'd never bet).
  BACKABLE : held-out games in the top quartile of that stat's projection -- the
             high-volume players Sportsbet actually posts deep N+ ladders for.

Lower relative error => tighter floors => more reliable value. The BACKABLE column
is the one that matters; the ALL column shows how much low-volume noise inflates it.
"""
import numpy as np

import backtest as B
import matchup as M

STATS = ["disposals", "fantasy", "hit_outs", "tackles", "clearances"]


def rel_for(df, stat):
    rec = B.collect(df, stat)
    if not len(rec):
        return None
    actual = rec["actual"].to_numpy()
    # current live blend prediction per row (with/without H2H regimes)
    pred = np.empty(len(rec))
    with_df, without_df = B.split(rec)
    for sub, h2h in [(with_df, True), (without_df, False)]:
        if len(sub):
            cols = B.feature_cols(B.FORM_WINDOWS, h2h)
            pred[sub.index] = sub[cols].to_numpy() @ B.current_weights(B.FORM_WINDOWS, h2h)
    err = np.abs(pred - actual)

    def rel(mask):
        a, e = actual[mask], err[mask]
        return e.mean() / a.mean(), e.mean(), a.mean(), int(mask.sum())

    q75 = np.quantile(pred, 0.75)
    return {"all": rel(np.ones(len(rec), bool)),
            "backable": rel(pred >= q75),
            "cv": float(np.std(actual) / np.mean(actual))}


def main():
    df = M.load("games_2022_2026.csv")
    print(f"\n{'stat':12s}{'relMAE ALL':>12}{'relMAE BACKABLE':>17}{'MAE/mean (backable)':>22}")
    print("-" * 63)
    rows = []
    for s in STATS:
        r = rel_for(df, s)
        if not r:
            print(f"{s:12s}  (no rows)"); continue
        ra, ea, aa, na = r["all"]
        rb, eb, ab, nb = r["backable"]
        rows.append((rb, s, ra, rb, eb, ab))
        print(f"{s:12s}{ra:>11.1%}{rb:>16.1%}{f'{eb:.1f} / {ab:.1f}':>22}")
    print("\nranked by BACKABLE relative error (best betting consistency first):")
    for rb, s, ra, _rb, eb, ab in sorted(rows):
        print(f"  {s:12s} {rb:5.1%}")


if __name__ == "__main__":
    main()
