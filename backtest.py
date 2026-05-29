"""
Backtest the projection weightings against actual per-game outcomes.

Walk-forward, no leakage: for every game we treat it as the held-out target and
rebuild the model's inputs (recent form / L5, season average, recency-weighted
head-to-head) using ONLY the player's earlier games. We then compare the blended
projection to what the player actually did.

    python backtest.py                 # full walk-forward tune + report
    python backtest.py --last-only     # only each player's final 2026 game
    python backtest.py --stat goals     # goals instead of disposals

Because a row's projection depends on exactly one weight set (the with-H2H blend
if the player has met this opponent before, otherwise the without-H2H blend), the
two sets are tuned independently. We report current vs grid-optimal, with 5-fold
cross-validation so the "best" weights aren't just in-sample overfit.
"""
import argparse
import numpy as np
import pandas as pd

import matchup as M

CURRENT_SEASON = M.CURRENT_SEASON
FORM_GAMES = M.FORM_GAMES


# ── Build leakage-free training records ──────────────────────────────────────────

def collect(df: pd.DataFrame, stat: str, min_prior_season: int = 3,
            last_only: bool = False) -> np.ndarray:
    """Return an (N, 4) array of [form, h2h, season_avg, actual] per held-out game.

    h2h is NaN when the player has no prior meeting with that opponent. Inputs use
    only games strictly before the target; form/season are scoped to the target's
    own season (mirroring the live model's "current season" framing)."""
    df = df[df[stat].notna()]   # a missing stat means the player didn't feature
    records = []
    for (_player, _team), g in df.groupby(["player", "team"], sort=False):
        rows = g.sort_values(["season", "round"]).to_dict("records")
        targets = [len(rows) - 1] if last_only else range(len(rows))
        for i in targets:
            if i <= 0:
                continue
            tgt = rows[i]
            if last_only and tgt["season"] != CURRENT_SEASON:
                continue
            prior = rows[:i]
            sp = [r for r in prior if r["season"] == tgt["season"]]
            if len(sp) < min_prior_season:
                continue
            form = np.mean([r[stat] for r in sp[-FORM_GAMES:]])
            season_avg = np.mean([r[stat] for r in sp])
            h2h_g = [r for r in prior if r["opponent"] == tgt["opponent"]]
            if h2h_g:
                # recency weight relative to the target season (recent meetings count more)
                w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in h2h_g], float)
                v = np.array([r[stat] for r in h2h_g], float)
                h2h = float((v * w).sum() / w.sum())
            else:
                h2h = np.nan
            records.append((form, h2h, season_avg, float(tgt[stat])))
    return np.array(records, float)


# ── Prediction + metrics ─────────────────────────────────────────────────────────

def predict(rec: np.ndarray, w_with, w_without) -> np.ndarray:
    """w_with=(form,h2h,season); w_without=(form,season)."""
    form, h2h, season, _ = rec.T
    has = ~np.isnan(h2h)
    h2h0 = np.nan_to_num(h2h)
    pred = np.where(
        has,
        w_with[0] * form + w_with[1] * h2h0 + w_with[2] * season,
        w_without[0] * form + w_without[1] * season,
    )
    return pred


def metrics(pred, actual) -> dict:
    err = pred - actual
    return {"MAE": float(np.mean(np.abs(err))),
            "RMSE": float(np.sqrt(np.mean(err ** 2))),
            "bias": float(np.mean(err))}


# ── Grid search (per subset, independent) ────────────────────────────────────────

def grid_with(rec: np.ndarray, step: float = 0.05):
    """Best (form,h2h,season) on the H2H subset, minimising MAE."""
    has = ~np.isnan(rec[:, 1])
    sub = rec[has]
    if len(sub) < 10:
        return None
    form, h2h, season, actual = sub.T
    best = (None, np.inf)
    grid = np.round(np.arange(0, 1 + 1e-9, step), 4)
    for f in grid:
        for h in grid[grid <= 1 - f + 1e-9]:
            s = round(1 - f - h, 4)
            if s < -1e-9:
                continue
            pred = f * form + h * h2h + s * season
            mae = np.mean(np.abs(pred - actual))
            if mae < best[1]:
                best = ((float(f), float(h), float(s)), mae)
    return best


def grid_without(rec: np.ndarray, step: float = 0.05):
    """Best (form,season) on the no-H2H subset, minimising MAE."""
    sub = rec[np.isnan(rec[:, 1])]
    if len(sub) < 10:
        return None
    form, _h, season, actual = sub.T
    best = (None, np.inf)
    for f in np.round(np.arange(0, 1 + 1e-9, step), 4):
        s = round(1 - f, 4)
        pred = f * form + s * season
        mae = np.mean(np.abs(pred - actual))
        if mae < best[1]:
            best = ((float(f), float(s)), mae)
    return best


def kfold_mae(rec: np.ndarray, subset: str, k: int = 5, step: float = 0.05,
              seed: int = 0) -> tuple[float, float]:
    """(current_weights_MAE, grid_optimal_MAE) under k-fold CV on a subset.
    The optimum is fitted on each train fold and scored on its test fold, so it
    reflects out-of-sample performance, not in-sample overfit."""
    if subset == "with":
        sub = rec[~np.isnan(rec[:, 1])]
        cur = (M.W_WITH_H2H["form"], M.W_WITH_H2H["h2h"], M.W_WITH_H2H["season"])
        fit = grid_with
        score = lambda w, r: np.abs((w[0] * r[:, 0] + w[1] * r[:, 1] + w[2] * r[:, 2]) - r[:, 3])
    else:
        sub = rec[np.isnan(rec[:, 1])]
        cur = (M.W_WITHOUT_H2H["form"], M.W_WITHOUT_H2H["season"])
        fit = grid_without
        score = lambda w, r: np.abs((w[0] * r[:, 0] + w[1] * r[:, 2]) - r[:, 3])
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(sub))
    folds = np.array_split(idx, k)
    cur_e, opt_e = [], []
    for j in range(k):
        test = sub[folds[j]]
        train = sub[np.concatenate([folds[m] for m in range(k) if m != j])]
        cur_e.append(score(cur, test))
        w_opt = fit(train, step)[0]
        opt_e.append(score(w_opt, test))
    return float(np.mean(np.concatenate(cur_e))), float(np.mean(np.concatenate(opt_e)))


# ── Report ───────────────────────────────────────────────────────────────────────

def report(df: pd.DataFrame, stat: str, last_only: bool):
    rec = collect(df, stat, last_only=last_only)
    n = len(rec)
    n_h2h = int(np.sum(~np.isnan(rec[:, 1])))
    label = "final-2026-game-per-player" if last_only else "walk-forward (all games)"
    print(f"\n{'='*70}\n  {stat.upper()}  —  {label}")
    print(f"  {n} held-out games  ({n_h2h} with prior H2H, {n - n_h2h} without)\n{'='*70}")

    form, h2h, season, actual = rec.T

    # Baselines
    base = {
        "season avg only": season,
        "L5 (form) only": form,
        "current blend": predict(rec,
                                 (M.W_WITH_H2H["form"], M.W_WITH_H2H["h2h"], M.W_WITH_H2H["season"]),
                                 (M.W_WITHOUT_H2H["form"], M.W_WITHOUT_H2H["season"])),
    }
    print(f"  {'predictor':<24}{'MAE':>8}{'RMSE':>8}{'bias':>8}")
    print(f"  {'-'*46}")
    for name, pred in base.items():
        m = metrics(pred, actual)
        print(f"  {name:<24}{m['MAE']:>8.3f}{m['RMSE']:>8.3f}{m['bias']:>+8.3f}")

    # Grid optimum (in-sample) per subset
    gw, gwo = grid_with(rec), grid_without(rec)
    print(f"\n  grid-optimal weights (in-sample MAE):")
    if gw:
        (f, h, s), mae = gw
        print(f"    with H2H   : form={f:.2f} h2h={h:.2f} season={s:.2f}   "
              f"(MAE {mae:.3f} vs current "
              f"{metrics(predict(rec[~np.isnan(rec[:,1])], (M.W_WITH_H2H['form'],M.W_WITH_H2H['h2h'],M.W_WITH_H2H['season']), (0,0)), rec[~np.isnan(rec[:,1])][:,3])['MAE']:.3f})")
    if gwo:
        (f, s), mae = gwo
        print(f"    without H2H: form={f:.2f} season={s:.2f}            (MAE {mae:.3f})")

    # 5-fold CV (out-of-sample): does the optimum actually generalise?
    print(f"\n  5-fold CV MAE (out-of-sample):")
    for subset, name in [("with", "with H2H"), ("without", "without H2H")]:
        try:
            cur, opt = kfold_mae(rec, subset)
            tag = "  <- improves" if opt < cur - 1e-4 else ("  ~ no gain" if abs(opt-cur) <= 1e-4 else "  (worse)")
            print(f"    {name:<12}: current {cur:.3f}   tuned {opt:.3f}{tag}")
        except Exception as e:
            print(f"    {name:<12}: n/a ({e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2024_2026.csv")
    ap.add_argument("--stat", choices=["disposals", "goals"], default="disposals")
    ap.add_argument("--last-only", action="store_true",
                    help="only each player's final 2026 game (the literal 'predict the last match')")
    ap.add_argument("--both", action="store_true", help="report disposals and goals")
    args = ap.parse_args()

    df = M.load(args.csv)
    stats = ["disposals", "goals"] if args.both else [args.stat]
    for st in stats:
        report(df, st, args.last_only)


if __name__ == "__main__":
    main()
