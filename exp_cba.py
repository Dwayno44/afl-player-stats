"""
Spike experiment: does CBA add signal beyond the box score?

Uses the API-sourced frame from fetch_cba.py (disposals, fantasy=dreamTeamPoints,
pct_played, cba_pct), so the baseline blend and the CBA test run on identical rows.

The hypothesis from experiment #2: CBA is an EARLY role signal. When a player's
recent CBA% rises above their season baseline (a teammate is hurt, role expands),
their output jumps before the season-anchored blend catches up. So a recent-CBA
TREND, computed from prior games only (fully pre-game-knowable), should explain
part of the residual the baseline leaves behind.

Walk-forward, leakage-free. We fit a single coefficient on the CBA trend by least
squares on each TRAIN fold (resid ~ b * trend) and score on the held-out fold, so
the reported gain is out-of-sample, not curve-fit.

    python exp_cba.py --both
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

            # CBA trend from prior games only: recent (last 3) vs season baseline.
            cbas = [r["cba_pct"] for r in sp if pd.notna(r["cba_pct"])]
            trend, recent = np.nan, np.nan
            if len(cbas) >= 3:
                recent = float(np.mean(cbas[-3:]))
                trend = recent - float(np.mean(cbas))     # >0 role expanding
            out.append({"baseline": base, "actual": float(rec[stat]),
                        "cba_trend": trend, "cba_recent": recent})
        phist[key].append(rec)
    return pd.DataFrame(out)


def cv_gain(rec, feat, k=5, seed=0):
    """Out-of-sample MAE for baseline vs baseline + b*feature, b fit per train fold."""
    d = rec.dropna(subset=[feat]).reset_index(drop=True)
    base = d["baseline"].to_numpy(); act = d["actual"].to_numpy(); x = d[feat].to_numpy()
    resid = act - base
    rng = np.random.default_rng(seed); idx = rng.permutation(len(d))
    folds = np.array_split(idx, k)
    be, ae = [], []
    for j in range(k):
        te = folds[j]; tr = np.concatenate([folds[m] for m in range(k) if m != j])
        xt = x[tr] - x[tr].mean()
        b = float((xt @ resid[tr]) / (xt @ xt)) if (xt @ xt) > 0 else 0.0
        adj = base[te] + b * (x[te] - x[tr].mean())
        be.append(np.abs(base[te] - act[te])); ae.append(np.abs(adj - act[te]))
    return np.concatenate(be).mean(), np.concatenate(ae).mean(), len(d)


def report(df, stat):
    rec = collect(df, stat)
    a = rec["actual"].to_numpy(); base = rec["baseline"].to_numpy()
    mae_base = float(np.mean(np.abs(base - a)))
    print(f"\n{'='*64}\n  {stat.upper()}  —  does CBA trend beat the box-score blend?")
    print(f"  {len(rec)} held-out games  (baseline MAE {mae_base:.3f})\n{'='*64}")

    has_cba = rec.dropna(subset=["cba_trend"])
    r = has_cba["actual"] - has_cba["baseline"]
    print(f"  rows with CBA history: {len(has_cba)}")
    print(f"  corr(CBA trend,  residual) = {np.corrcoef(has_cba['cba_trend'], r)[0,1]:+.3f}")
    print(f"  corr(CBA recent, residual) = {np.corrcoef(has_cba['cba_recent'], r)[0,1]:+.3f}")

    for feat in ["cba_trend", "cba_recent"]:
        b, ad, n = cv_gain(rec, feat)
        d = ad - b
        tag = "improves" if d < -1e-3 else ("~no gain" if abs(d) <= 1e-3 else "worse")
        print(f"  +{feat:<11} (n={n}): baseline {b:.3f} -> {ad:.3f}  ({d:+.3f}, {d/b*100:+.1f}%)  {tag}")

    # Role-change subset: biggest |trend| quartile, where CBA should matter most.
    hc = has_cba.copy()
    thr = hc["cba_trend"].abs().quantile(0.75)
    big = hc[hc["cba_trend"].abs() >= thr]
    if len(big) > 20:
        bb = float(np.mean(np.abs(big["baseline"] - big["actual"])))
        # apply a global trend coefficient fit on the rest
        rest = hc[hc["cba_trend"].abs() < thr]
        xt = rest["cba_trend"] - rest["cba_trend"].mean()
        bcoef = float((xt @ (rest["actual"] - rest["baseline"])) / (xt @ xt))
        adj = big["baseline"] + bcoef * (big["cba_trend"] - rest["cba_trend"].mean())
        ba = float(np.mean(np.abs(adj - big["actual"])))
        print(f"  role-change subset (top-25% |trend|, n={len(big)}): "
              f"baseline {bb:.3f} -> CBA-adj {ba:.3f}  ({ba-bb:+.3f})")


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
