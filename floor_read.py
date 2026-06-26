"""One-off floor calibration on the R14 Bulldogs v Adelaide opener (no snapshot
existed, so we recompute pre-game floors from the CSV — which is pre-R14, hence
leakage-free — and grade vs AFL API actuals)."""
import numpy as np
import matchup as M
import scorecard as SC

df = M.load("games_2022_2026.csv")
actuals, played = SC.api_actuals(2026, 14)

rows = []
for team, opp in [("Western Bulldogs", "Adelaide"), ("Adelaide", "Western Bulldogs")]:
    view = M.team_view(df, team, opp)
    for _, r in view.iterrows():
        a = actuals.get(SC._key(team, r["player"]))
        if a is None:
            continue  # didn't play
        rows.append({"team": team, "player": r["player"], "proj": r["D_proj"],
                     "floor": r["D_floor"], "actual": a})

import pandas as pd
g = pd.DataFrame(rows)
played_game = ("Western Bulldogs v Adelaide" in played) or any(
    "Bulldog" in x or "Adelaide" in x for x in played)
print(f"\nR14 Western Bulldogs v Adelaide -- floor calibration ({len(g)} players graded)")


def block(d, label):
    if not len(d):
        print(f"  {label}: none"); return
    hit = (d["actual"] >= d["floor"]).mean()
    err = d["actual"] - d["proj"]
    print(f"  {label:<22} n={len(d):3d}  floorHit {hit*100:5.1f}%  "
          f"projMAE {err.abs().mean():4.2f}  bias {err.mean():+4.2f}")


block(g, "all projected")
block(g[g["floor"] >= 10], "floor>=10 (shown)")
print("\n  shown picks that MISSED their floor:")
miss = g[(g["floor"] >= 10) & (g["actual"] < g["floor"])].sort_values("floor", ascending=False)
for _, r in miss.iterrows():
    print(f"    {r['player']:<22}{r['team'][:4]:>5}  floor {int(r['floor'])}  got {int(r['actual'])}")
