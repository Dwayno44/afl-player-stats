"""
Experiment #2 — does decomposing a stat into (per-minute rate x expected TOG)
beat projecting the raw total directly?

Walk-forward and leakage-free, mirroring backtest.collect(): for each held-out
game we rebuild inputs from the player's strictly-earlier games only. Both arms
use the SAME recency treatment (the live model's blend weights, windows, H2H),
so the only thing that differs is what gets blended:

  baseline : blend(prior raw totals)                      -> projection
  tog      : blend(prior per-minute rates) x blend(prior TOG)  -> projection

`rate = stat / pct_played` (production per 1% game time); `pct_played` is the
TOG proxy. Expected TOG is itself a blend of prior TOG with the same weights, so
the recency handling is identical across arms. We score both against the actual
total and report MAE / RMSE / bias on the same held-out set.

    python exp_tog.py                 # disposals
    python exp_tog.py --stat fantasy
    python exp_tog.py --both
"""
import argparse
import numpy as np
import pandas as pd

import matchup as M

CURRENT_SEASON = M.CURRENT_SEASON
FORM_WINDOWS = M.FORM_WINDOWS


def _blend(windows_vals: dict, h2h, season, has_h2h) -> float:
    """The live model's blend, applied to whatever quantity the dict holds."""
    return M.project(windows_vals, h2h, season, has_h2h)


def _h2h(prior, tgt, col):
    """Recency-weighted head-to-head average of `col` vs the target opponent."""
    g = [r for r in prior if r["opponent"] == tgt["opponent"]]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in g], float)
    v = np.array([r[col] for r in g], float)
    return float((v * w).sum() / w.sum())


def collect(df: pd.DataFrame, stat: str, min_prior_season: int = 3) -> pd.DataFrame:
    """One row per held-out game: baseline projection, TOG projection, actual."""
    df = df[df[stat].notna()].copy()
    df["_tog"] = pd.to_numeric(df["pct_played"], errors="coerce")
    # Per-minute rate; guard against the rare 0/NaN TOG so a sub game can't divide by zero.
    df["_rate"] = np.where(df["_tog"].to_numpy() > 0,
                           df[stat].to_numpy() / df["_tog"].to_numpy(), np.nan)
    out = []
    for (_player, _team), g in df.groupby(["player", "team"], sort=False):
        rows = g.sort_values(["season", "round"]).to_dict("records")
        for i in range(1, len(rows)):
            tgt = rows[i]
            prior = rows[:i]
            sp = [r for r in prior if r["season"] == tgt["season"]]
            if len(sp) < min_prior_season:
                continue
            # Require usable TOG history for the rate arm.
            sp_tog = [r for r in sp if r["_tog"] and r["_tog"] > 0 and not np.isnan(r["_rate"])]
            if len(sp_tog) < min_prior_season:
                continue

            def windows(col, src):
                return {f"L{w}": float(np.mean([r[col] for r in src[-w:]])) for w in FORM_WINDOWS}

            has_tot = bool([r for r in prior if r["opponent"] == tgt["opponent"]])

            # Baseline: blend raw totals.
            base = _blend(windows(stat, sp), _h2h(prior, tgt, stat),
                          float(np.mean([r[stat] for r in sp])), has_tot)

            # TOG arm: blend rates, blend TOG, multiply.
            rate_proj = _blend(windows("_rate", sp_tog), _h2h(prior, tgt, "_rate"),
                               float(np.mean([r["_rate"] for r in sp_tog])), has_tot)
            tog_proj = _blend(windows("_tog", sp_tog), _h2h(prior, tgt, "_tog"),
                              float(np.mean([r["_tog"] for r in sp_tog])), has_tot)
            tog = rate_proj * tog_proj
            # Oracle: same rate projection but using the TARGET game's true TOG.
            # This is the ceiling — how good the rate arm could be with a perfect
            # minutes signal. The gap (oracle - baseline) is the prize available to
            # any feature that predicts minutes better than the player's own average.
            oracle = rate_proj * tgt["_tog"] if tgt["_tog"] and tgt["_tog"] > 0 else tog

            out.append({"baseline": base, "tog": tog, "oracle": oracle,
                        "actual": float(tgt[stat]), "tgt_tog": tgt["_tog"]})
    return pd.DataFrame(out)


def metrics(pred, actual) -> dict:
    err = np.asarray(pred) - np.asarray(actual)
    return {"MAE": float(np.mean(np.abs(err))), "RMSE": float(np.sqrt(np.mean(err ** 2))),
            "bias": float(np.mean(err))}


def report(df, stat):
    rec = collect(df, stat)
    a = rec["actual"].to_numpy()
    mb = metrics(rec["baseline"], a)
    mt = metrics(rec["tog"], a)
    mo = metrics(rec["oracle"], a)
    print(f"\n{'='*64}\n  {stat.upper()}  —  raw-total vs (rate x expected-TOG)")
    print(f"  {len(rec)} held-out games (walk-forward, leakage-free)\n{'='*64}")
    print(f"  {'model':<26}{'MAE':>9}{'RMSE':>9}{'bias':>9}")
    print(f"  {'-'*53}")
    print(f"  {'baseline (raw total)':<26}{mb['MAE']:>9.3f}{mb['RMSE']:>9.3f}{mb['bias']:>+9.3f}")
    print(f"  {'TOG (rate x est. minutes)':<26}{mt['MAE']:>9.3f}{mt['RMSE']:>9.3f}{mt['bias']:>+9.3f}")
    print(f"  {'ORACLE (rate x TRUE mins)':<26}{mo['MAE']:>9.3f}{mo['RMSE']:>9.3f}{mo['bias']:>+9.3f}")
    dMAE = mt['MAE'] - mb['MAE']
    dOra = mo['MAE'] - mb['MAE']
    print(f"  {'-'*53}")
    print(f"  delta MAE {dMAE:+.3f}  ({dMAE/mb['MAE']*100:+.1f}%)   "
          f"{'TOG wins' if dMAE < -1e-4 else ('no change' if abs(dMAE)<=1e-4 else 'baseline wins')}")
    print(f"  ORACLE ceiling {dOra:+.3f}  ({dOra/mb['MAE']*100:+.1f}%)  "
          f"<- the prize if minutes were predicted perfectly")
    # Where does TOG help most? Split by how far the target game's TOG sits from
    # the player's projected minutes is not available here, but unusual-TOG games
    # (managed/blowout/return) are exactly where the decomposition should pay off.
    lowt = rec[rec["tgt_tog"] < 70]
    if len(lowt):
        lb, lt = metrics(lowt["baseline"], lowt["actual"]), metrics(lowt["tog"], lowt["actual"])
        print(f"  on low-TOG games (<70%, n={len(lowt)}): "
              f"baseline {lb['MAE']:.2f}  ->  TOG {lt['MAE']:.2f}  ({lt['MAE']-lb['MAE']:+.2f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    ap.add_argument("--stat", choices=["disposals", "fantasy", "goals"], default="disposals")
    ap.add_argument("--both", action="store_true", help="disposals and fantasy")
    args = ap.parse_args()
    df = M.load(args.csv)
    for st in (["disposals", "fantasy"] if args.both else [args.stat]):
        report(df, st)


if __name__ == "__main__":
    main()
