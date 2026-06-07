"""
Experiment #9 — game script (expected margin / blowout) ceiling.

We have no historical betting lines, so we can't backtest the real feature. But we
CAN reconstruct each game's margin from the per-player scores in the CSV
(team score = sum of goals*6 + behinds over the team's line-up), and run an ORACLE:
feed the TRUE margin in and measure how much projection error is recoverable if
game script were known perfectly. The betting line is a (noisy) pre-game estimate
of exactly this margin, so the oracle is the ceiling on what a line could buy.

Two oracle adjustments, fit on actual margins (hence "oracle", in-sample ceiling):
  - blowout bucket: mean residual (actual - baseline) within |margin| x won/lost
    buckets, added back. Captures "favourites' players rest / underdogs' defenders
    see more ball" if such a systematic bias exists.
  - linear: a single slope on signed margin.

If even the oracle barely helps, the betting line is not worth sourcing.

    python exp_gamescript.py --both
"""
import argparse
from collections import defaultdict
import numpy as np
import pandas as pd

import matchup as M

FORM_WINDOWS = M.FORM_WINDOWS


def _h2h(prior, tgt, col):
    g = [r for r in prior if r["opponent"] == tgt["opponent"]]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in g], float)
    v = np.array([r[col] for r in g], float)
    return float((v * w).sum() / w.sum())


def collect(df: pd.DataFrame, stat: str, min_prior_season: int = 3) -> pd.DataFrame:
    df = df[df[stat].notna()].copy()
    df = df.sort_values(["season", "round"]).reset_index(drop=True)
    g6 = pd.to_numeric(df["goals"], errors="coerce").fillna(0) * 6
    bh = pd.to_numeric(df["behinds"], errors="coerce").fillna(0)
    df["_pts"] = g6 + bh
    # Team score per (season, round, team) = sum of its players' points.
    team_score = df.groupby(["season", "round", "team"])["_pts"].sum().to_dict()

    phist = defaultdict(list)
    out = []
    for rec in df.to_dict("records"):
        key = (rec["player"], rec["team"])
        prior = phist[key]
        sp = [r for r in prior if r["season"] == rec["season"]]
        if len(sp) >= min_prior_season:
            windows = {f"L{w}": float(np.mean([r[stat] for r in sp[-w:]])) for w in FORM_WINDOWS}
            season_avg = float(np.mean([r[stat] for r in sp]))
            has = bool([r for r in prior if r["opponent"] == rec["opponent"]])
            base = M.project(windows, _h2h(prior, rec, stat), season_avg, has)
            ours = team_score.get((rec["season"], rec["round"], rec["team"]))
            theirs = team_score.get((rec["season"], rec["round"], rec["opponent"]))
            margin = (ours - theirs) if (ours is not None and theirs is not None) else np.nan
            out.append({"baseline": base, "actual": float(rec[stat]), "margin": margin})
        phist[key].append(rec)
    return pd.DataFrame(out)


def metrics(pred, actual) -> dict:
    err = np.asarray(pred) - np.asarray(actual)
    return {"MAE": float(np.mean(np.abs(err))), "RMSE": float(np.sqrt(np.mean(err ** 2)))}


def report(df, stat):
    rec = collect(df, stat).dropna(subset=["margin"])
    a = rec["actual"].to_numpy()
    base = rec["baseline"].to_numpy()
    margin = rec["margin"].to_numpy()
    resid = a - base
    mb = metrics(base, a)

    # Oracle 1: bucketed mean residual by signed-margin band.
    bands = [-1e9, -50, -25, -10, 10, 25, 50, 1e9]
    idx = np.digitize(margin, bands)
    add = np.zeros_like(base)
    for b in np.unique(idx):
        m = idx == b
        add[m] = resid[m].mean()
    mo1 = metrics(base + add, a)

    # Oracle 2: single linear slope on signed margin (least squares on residual).
    s = np.polyfit(margin, resid, 1)
    mo2 = metrics(base + np.polyval(s, margin), a)

    print(f"\n{'='*62}\n  {stat.upper()}  —  game-script (margin) oracle ceiling")
    print(f"  {len(rec)} held-out games\n{'='*62}")
    print(f"  {'model':<28}{'MAE':>9}{'RMSE':>9}")
    print(f"  {'-'*46}")
    print(f"  {'baseline':<28}{mb['MAE']:>9.3f}{mb['RMSE']:>9.3f}")
    for name, m in [("oracle: margin buckets", mo1), ("oracle: linear margin", mo2)]:
        d = m['MAE'] - mb['MAE']
        print(f"  {name:<28}{m['MAE']:>9.3f}{m['RMSE']:>9.3f}  ({d:+.3f}, {d/mb['MAE']*100:+.1f}%)")
    corr = np.corrcoef(margin, resid)[0, 1]
    print(f"  corr(signed margin, residual) = {corr:+.3f}   slope = {s[0]:+.4f} per point")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    ap.add_argument("--stat", choices=["disposals", "fantasy", "goals"], default="disposals")
    ap.add_argument("--both", action="store_true")
    args = ap.parse_args()
    df = M.load(args.csv)
    for st in (["disposals", "fantasy"] if args.both else [args.stat]):
        report(df, st)


if __name__ == "__main__":
    main()
