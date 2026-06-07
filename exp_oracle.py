"""
Decisive spike: is the recoverable projection error about MINUTES or ROLE?

On the API frame (fetch_cba.py: disposals, fantasy, pct_played=TOG, cba_pct), all
on identical rows, we measure oracle ceilings — how much MAE is recoverable if we
knew a given target-game quantity perfectly:

  baseline            : the live blend (form + season + H2H)
  TOG oracle          : rate_proj x TRUE target TOG          (the #2 headline)
  TOG-dev oracle      : baseline + b*(TRUE TOG - expected TOG)
  CBA-dev oracle      : baseline + b*(TRUE cba% - baseline cba%)
  TOG+CBA-dev oracle  : both deviations together

Oracle coefficients are fit out-of-sample (per train fold) on the residual, so the
ceilings are honest. If TOG-dev recovers the error and CBA-dev adds little on top,
the prize is MINUTES (rotation/cap/blowout), not ROLE — which decides whether the
forward signal to source is a minutes/rotation model or CBA team-news.

    python exp_oracle.py --both
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


def collect(df, stat, min_prior_season=3):
    df = df[df[stat].notna()].copy()
    df = df.sort_values(["season", "round"]).reset_index(drop=True)
    df["_rate"] = np.where(df["pct_played"].to_numpy() > 0,
                           df[stat].to_numpy() / df["pct_played"].to_numpy(), np.nan)
    phist = defaultdict(list)
    out = []
    for rec in df.to_dict("records"):
        key = (rec["player"], rec["team"]); prior = phist[key]
        sp = [r for r in prior if r["season"] == rec["season"]]
        spt = [r for r in sp if r["pct_played"] and r["pct_played"] > 0 and pd.notna(r["_rate"])]
        if len(sp) >= min_prior_season and len(spt) >= min_prior_season:
            def W(col, src): return {f"L{w}": float(np.mean([r[col] for r in src[-w:]])) for w in FORM_WINDOWS}
            has = bool([r for r in prior if r["opponent"] == rec["opponent"]])
            base = M.project(W(stat, sp), _h2h(prior, rec, stat),
                             float(np.mean([r[stat] for r in sp])), has)
            rate_proj = M.project(W("_rate", spt), _h2h(prior, rec, "_rate"),
                                  float(np.mean([r["_rate"] for r in spt])), has)
            exp_tog = M.project(W("pct_played", spt), _h2h(prior, rec, "pct_played"),
                                float(np.mean([r["pct_played"] for r in spt])), has)
            cbas = [r["cba_pct"] for r in sp if pd.notna(r["cba_pct"])]
            base_cba = float(np.mean(cbas)) if len(cbas) >= 3 else np.nan
            out.append({
                "baseline": base, "actual": float(rec[stat]),
                "rate_proj": rate_proj, "true_tog": rec["pct_played"], "exp_tog": exp_tog,
                "tog_dev": (rec["pct_played"] - exp_tog),
                "cba_dev": (rec["cba_pct"] - base_cba) if pd.notna(base_cba) and pd.notna(rec["cba_pct"]) else np.nan,
            })
        phist[key].append(rec)
    return pd.DataFrame(out)


def cv_multi(d, feats, k=5, seed=0):
    """OOS MAE of baseline + sum(b_i*feat_i), coefficients fit per train fold."""
    d = d.dropna(subset=feats).reset_index(drop=True)
    base = d["baseline"].to_numpy(); act = d["actual"].to_numpy()
    X = d[feats].to_numpy(); resid = act - base
    rng = np.random.default_rng(seed); idx = rng.permutation(len(d))
    folds = np.array_split(idx, k); be, ae = [], []
    for j in range(k):
        te = folds[j]; tr = np.concatenate([folds[m] for m in range(k) if m != j])
        mu = X[tr].mean(0); Xt = X[tr] - mu
        b, *_ = np.linalg.lstsq(Xt, resid[tr], rcond=None)
        adj = base[te] + (X[te] - mu) @ b
        be.append(np.abs(base[te] - act[te])); ae.append(np.abs(adj - act[te]))
    return np.concatenate(be).mean(), np.concatenate(ae).mean(), len(d)


def report(df, stat):
    rec = collect(df, stat)
    a = rec["actual"].to_numpy(); base = rec["baseline"].to_numpy()
    mb = float(np.mean(np.abs(base - a)))
    # rate x true TOG (the multiplicative #2 oracle)
    ro = rec.dropna(subset=["rate_proj", "true_tog"])
    mo = float(np.mean(np.abs(ro["rate_proj"] * ro["true_tog"] - ro["actual"])))
    print(f"\n{'='*66}\n  {stat.upper()}  —  minutes vs role: oracle ceilings")
    print(f"  {len(rec)} held-out games (API 2025-26)\n{'='*66}")
    print(f"  {'baseline':<30}{mb:>8.3f}")
    print(f"  {'rate x TRUE TOG (oracle)':<30}{mo:>8.3f}   ({mo-mb:+.3f}, {(mo-mb)/mb*100:+.1f}%)")
    for label, feats in [("+ TOG deviation (oracle)", ["tog_dev"]),
                         ("+ CBA deviation (oracle)", ["cba_dev"]),
                         ("+ TOG & CBA dev (oracle)", ["tog_dev", "cba_dev"])]:
        b, ad, n = cv_multi(rec, feats)
        print(f"  {label:<30}{ad:>8.3f}   ({ad-b:+.3f}, {(ad-b)/b*100:+.1f}%)  n={n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="cba_games.csv")
    ap.add_argument("--stat", choices=["disposals", "fantasy"], default="disposals")
    ap.add_argument("--both", action="store_true")
    args = ap.parse_args()
    df = pd.read_csv(args.csv)
    for c in ["disposals", "fantasy", "pct_played", "cba_pct"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for st in (["disposals", "fantasy"] if args.both else [args.stat]):
        report(df, st)


if __name__ == "__main__":
    main()
