"""
Floor-calibration backtest for hit-outs (ruck markets).

The betting model sets a confidence floor = proj - z(conf)*sigma and treats it as
"clears N at conf%". MAE (backtest.py) tells us the projection is roughly right,
but for *betting* what matters is whether the floor's stated confidence is honest:
if we call something an 85% floor, does the ruck actually clear it ~85% of the
time? Hit-outs are higher-variance and right-skewed (max ~68 vs mean ~15 for
rucks), so a symmetric Normal floor could be miscalibrated.

Walk-forward, no leakage: for each held-out ruck game we rebuild proj and sigma
from ONLY that player's earlier same-season games (mirroring the live model's
recent_for_team / disposal_floor), then measure the empirical clear rate of the
floor at several confidence levels.

    python hitouts_calib.py
    python hitouts_calib.py --stat disposals   # sanity-check vs the calibrated stat
"""
import argparse
from statistics import NormalDist

import numpy as np
import pandas as pd

import matchup as M

CONFS = (0.75, 0.80, 0.85, 0.90)


def calibrate(df: pd.DataFrame, stat: str, min_prior: int = 8,
              floor_games: int = M.FLOOR_GAMES):
    """Walk-forward floor calibration. Returns a list of per-game records with the
    floor at each confidence and whether the actual cleared it."""
    df = df[df[stat].notna()]
    recs = []
    for (_player, _team), g in df.groupby(["player", "team"], sort=False):
        rows = g.sort_values(["season", "round"]).to_dict("records")
        for i in range(len(rows)):
            tgt = rows[i]
            prior = rows[:i]
            sp = [r for r in prior if r["season"] == tgt["season"]]
            if len(sp) < min_prior:                       # need a stable sigma
                continue
            forms = {f"L{w}": float(np.mean([r[stat] for r in sp[-w:]]))
                     for w in M.FORM_WINDOWS}
            season = float(np.mean([r[stat] for r in sp]))
            h2h_g = [r for r in prior if r["opponent"] == tgt["opponent"]]
            if h2h_g:
                w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in h2h_g], float)
                v = np.array([r[stat] for r in h2h_g], float)
                h2h, has = float((v * w).sum() / w.sum()), True
            else:
                h2h, has = float("nan"), False
            proj = M.project(forms, h2h, season, has)
            recent = [r[stat] for r in sp[-floor_games:]]
            sigma = float(np.std(recent, ddof=1))
            actual = float(tgt[stat])
            rec = {"proj": proj, "sigma": sigma, "actual": actual}
            for c in CONFS:
                margin = NormalDist().inv_cdf(c) * sigma
                floor = max(0.0, np.floor(proj - margin))
                rec[f"floor{int(c*100)}"] = floor
                rec[f"clear{int(c*100)}"] = float(actual >= floor)
            recs.append(rec)
    return pd.DataFrame(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    ap.add_argument("--stat", default="hit_outs",
                    choices=["hit_outs", "disposals", "tackles", "clearances", "fantasy"])
    args = ap.parse_args()

    df = M.load(args.csv)
    r = calibrate(df, args.stat)
    print(f"\n{'='*64}\n  FLOOR CALIBRATION  —  {args.stat}   ({len(r)} held-out games)\n{'='*64}")
    print(f"  proj/actual mean: {r['proj'].mean():.1f} / {r['actual'].mean():.1f}"
          f"   sigma mean: {r['sigma'].mean():.1f}")
    print(f"\n  {'conf':>5}{'target':>8}{'empirical':>11}{'mean floor':>12}{'floor=0 %':>11}")
    print(f"  {'-'*45}")
    for c in CONFS:
        cc = int(c * 100)
        emp = r[f"clear{cc}"].mean()
        mf = r[f"floor{cc}"].mean()
        z0 = (r[f"floor{cc}"] == 0).mean() * 100
        flag = "  ok" if emp >= c else "  <- under target"
        print(f"  {cc:>4}%{c:>8.0%}{emp:>11.1%}{mf:>12.1f}{z0:>10.1f}%{flag}")


if __name__ == "__main__":
    main()
