"""
Historical floor calibration — how often does the 85% disposal floor actually hold,
across the full backtest (not just the 2 live rounds)?

Walk-forward, leakage-free on games_2022_2026.csv: for every player-game, rebuild
the SAME projection + floor the live page uses from prior games only, and check
actual >= floor. Reports the hit rate for the shown slate (floor>=10) and overall,
per season, so we can state the real evidence base behind the 85% claim.
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from statistics import NormalDist
import matchup as M

Z = NormalDist().inv_cdf(0.85)
FW = M.FORM_WINDOWS


def _h2h(prior, opp, season):
    g = [r for r in prior if r["opponent"] == opp]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (season - 3)) for r in g], float)
    return float((np.array([r["disposals"] for r in g], float) * w).sum() / w.sum())


def main():
    df = M.load("games_2022_2026.csv")
    df = df[df["disposals"].notna()].sort_values(["season", "round"]).reset_index(drop=True)
    phist = defaultdict(list)
    rows = []
    for rec in df.to_dict("records"):
        s, opp = rec["season"], rec["opponent"]
        prior = phist[(rec["player"], rec["team"])]
        sp = [x for x in prior if x["season"] == s]
        if len(sp) >= 3:
            d = [x["disposals"] for x in sp]
            proj = M.project({f"L{w}": float(np.mean(d[-w:])) for w in FW},
                             _h2h(prior, opp, s), float(np.mean(d)),
                             pd.notna(_h2h(prior, opp, s)))
            sigma = float(np.std(d[-15:]))
            floor = max(0, np.floor(proj - Z * sigma))
            rows.append({"season": s, "actual": float(rec["disposals"]),
                         "floor": floor, "shown": floor >= 10})
        phist[(rec["player"], rec["team"])].append(rec)
    r = pd.DataFrame(rows)
    r["hit"] = (r["actual"] >= r["floor"]).astype(int)
    sh = r[r["shown"]]
    print(f"\n  HISTORICAL FLOOR CALIBRATION (85% target, walk-forward 2022-26)")
    print(f"  {'-'*54}")
    print(f"  all projected : {len(r):6d} games   floor held {r['hit'].mean()*100:.1f}%")
    print(f"  shown (>=10)  : {len(sh):6d} games   floor held {sh['hit'].mean()*100:.1f}%")
    print("\n  per season (shown floor>=10):")
    for s, g in sh.groupby("season"):
        print(f"    {s}: {len(g):5d} games   {g['hit'].mean()*100:.1f}%")


if __name__ == "__main__":
    main()
