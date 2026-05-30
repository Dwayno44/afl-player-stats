"""
Backtest the projection weightings against actual per-game outcomes.

Walk-forward, no leakage: for every game we treat it as the held-out target and
rebuild the model's inputs (form windows L3/L5/L10, season average, recency-
weighted head-to-head) using ONLY the player's earlier games. We then compare the
blended projection to what the player actually did.

    python backtest.py                 # full walk-forward tune + report
    python backtest.py --last-only     # only each player's final 2026 game
    python backtest.py --stat goals    # goals instead of disposals
    python backtest.py --windows 3,5,10

The live model blends one form term (L5) with H2H and season. This backtest
decomposes form into several windows (L3/L5/L10 by default) and tunes a weight
for each, so we can see whether a multi-window blend beats the single-L5 model.
A row's projection uses the with-H2H weight set if the player has met this
opponent before, otherwise the without-H2H set, so the two are tuned independently.
Grid optima are reported with 5-fold cross-validation so the "best" weights reflect
out-of-sample performance, not in-sample overfit of the (correlated) windows.
"""
import argparse
import numpy as np
import pandas as pd

import matchup as M

CURRENT_SEASON = M.CURRENT_SEASON
FORM_WINDOWS = (3, 5, 10)   # form-average windows tuned as separate features


# ── Build leakage-free training records ──────────────────────────────────────────

def collect(df: pd.DataFrame, stat: str, form_windows=FORM_WINDOWS,
            min_prior_season: int = 3, last_only: bool = False) -> pd.DataFrame:
    """One row per held-out game with the model inputs computed from prior games.

    Columns: one per form window (e.g. L3/L5/L10), `h2h`, `season`, `actual`.
    `h2h` is NaN when the player has no prior meeting with that opponent. Form and
    season are scoped to the target's own season (mirroring the live model's
    "current season" framing); inputs use only games strictly before the target.
    A short form window early in a season simply averages the games available, so
    L10 collapses toward the season average until ~10 games are on the board.
    """
    df = df[df[stat].notna()]   # a missing stat means the player didn't feature
    out = []
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
            rec = {f"L{w}": float(np.mean([r[stat] for r in sp[-w:]])) for w in form_windows}
            rec["season"] = float(np.mean([r[stat] for r in sp]))
            h2h_g = [r for r in prior if r["opponent"] == tgt["opponent"]]
            if h2h_g:
                # recency weight relative to the target season (recent meetings count more)
                w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in h2h_g], float)
                v = np.array([r[stat] for r in h2h_g], float)
                rec["h2h"] = float((v * w).sum() / w.sum())
            else:
                rec["h2h"] = np.nan
            rec["actual"] = float(tgt[stat])
            out.append(rec)
    return pd.DataFrame(out)


# ── Feature layout ────────────────────────────────────────────────────────────────

def feature_cols(form_windows, with_h2h: bool) -> list[str]:
    """Weighted features in a fixed order; weights over these sum to 1."""
    cols = [f"L{w}" for w in form_windows]
    return cols + (["h2h", "season"] if with_h2h else ["season"])


def current_weights(form_windows, with_h2h: bool) -> np.ndarray:
    """The live model's weights mapped onto the multi-window feature vector.

    Reads per-window keys (L3/L5/L10) when the live model carries them; falls back
    to a single `form` weight on L5 for the older single-window shape."""
    w = M.W_WITH_H2H if with_h2h else M.W_WITHOUT_H2H
    vec = [w.get(f"L{x}", w.get("form", 0.0) if x == 5 else 0.0) for x in form_windows]
    vec += [w["h2h"], w["season"]] if with_h2h else [w["season"]]
    return np.array(vec, float)


def split(rec: pd.DataFrame):
    """(with_h2h_rows, without_h2h_rows) — the two independently-tuned regimes."""
    has = rec["h2h"].notna()
    return rec[has], rec[~has]


# ── Grid search over the weight simplex ────────────────────────────────────────────

def _simplex(f: int, step: float) -> np.ndarray:
    """All non-negative weight vectors of length `f` summing to 1, on a `step` grid."""
    units = int(round(1 / step))
    out: list[list[int]] = []

    def rec(remaining: int, parts: list[int]):
        if len(parts) == f - 1:
            out.append(parts + [remaining])
            return
        for x in range(remaining + 1):
            rec(remaining - x, parts + [x])

    rec(units, [])
    return np.array(out, float) / units


def grid_search(X: np.ndarray, actual: np.ndarray, step: float, chunk: int = 4000):
    """Best weight vector (min MAE) over the simplex for feature matrix X.
    The simplex is scored in chunks so the (n_rows x n_combos) prediction block
    stays bounded regardless of grid resolution."""
    W = _simplex(X.shape[1], step)          # (K, F)
    best_w, best_mae = W[0], np.inf
    for c in range(0, len(W), chunk):
        Wc = W[c:c + chunk]
        mae = np.mean(np.abs(X @ Wc.T - actual[:, None]), axis=0)
        j = int(np.argmin(mae))
        if mae[j] < best_mae:
            best_mae, best_w = float(mae[j]), Wc[j]
    return best_w, best_mae


def fold_optima(X: np.ndarray, actual: np.ndarray, step: float, k: int = 5, seed: int = 0):
    """(mean_weights, std_weights) of the per-fold grid optima. Low std means the
    data agrees on the weighting across folds; high std flags an unstable split
    (expected when features are collinear, e.g. overlapping form windows)."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    folds = np.array_split(idx, k)
    ws = []
    for j in range(k):
        tr = np.concatenate([folds[m] for m in range(k) if m != j])
        w, _ = grid_search(X[tr], actual[tr], step)
        ws.append(w)
    W = np.array(ws)
    return W.mean(0), W.std(0)


def metrics(pred, actual) -> dict:
    err = pred - actual
    return {"MAE": float(np.mean(np.abs(err))),
            "RMSE": float(np.sqrt(np.mean(err ** 2))),
            "bias": float(np.mean(err))}


def cv_errors(X: np.ndarray, actual: np.ndarray, cur_w: np.ndarray,
              step: float, k: int = 5, seed: int = 0):
    """Per-row test errors under k-fold CV for (current weights, grid-tuned weights).
    The optimum is fitted on each train fold and scored on its held-out fold."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    folds = np.array_split(idx, k)
    cur_e, opt_e = [], []
    for j in range(k):
        te = folds[j]
        tr = np.concatenate([folds[m] for m in range(k) if m != j])
        w_opt, _ = grid_search(X[tr], actual[tr], step)
        cur_e.append(np.abs(X[te] @ cur_w - actual[te]))
        opt_e.append(np.abs(X[te] @ w_opt - actual[te]))
    return np.concatenate(cur_e), np.concatenate(opt_e)


# ── Report ───────────────────────────────────────────────────────────────────────

def _fmt_w(cols, w) -> str:
    return "  ".join(f"{c}={v:.2f}" for c, v in zip(cols, w) if v > 1e-9) or "(all zero)"


def report(df: pd.DataFrame, stat: str, form_windows, step: float, last_only: bool):
    rec = collect(df, stat, form_windows=form_windows, last_only=last_only)
    n = len(rec)
    with_df, without_df = split(rec)
    label = "final-2026-game-per-player" if last_only else "walk-forward (all games)"
    print(f"\n{'='*72}\n  {stat.upper()}  —  {label}   windows={form_windows} step={step}")
    print(f"  {n} held-out games  ({len(with_df)} with prior H2H, "
          f"{len(without_df)} without)\n{'='*72}")

    actual = rec["actual"].to_numpy()

    # Standalone predictors — how well each single window/average predicts alone.
    print(f"  {'standalone predictor':<24}{'MAE':>8}{'RMSE':>8}{'bias':>8}")
    print(f"  {'-'*48}")
    for col in [f"L{w}" for w in form_windows] + ["season"]:
        m = metrics(rec[col].to_numpy(), actual)
        print(f"  {col + ' only':<24}{m['MAE']:>8.3f}{m['RMSE']:>8.3f}{m['bias']:>+8.3f}")

    # Current single-L5 blend (the live model) as the baseline to beat.
    cur_pred = np.empty(n)
    for sub, h2h in [(with_df, True), (without_df, False)]:
        if len(sub):
            cols = feature_cols(form_windows, h2h)
            cur_pred[sub.index] = sub[cols].to_numpy() @ current_weights(form_windows, h2h)
    mcur = metrics(cur_pred, actual)
    print(f"  {'-'*48}")
    print(f"  {'current blend (L5)':<24}{mcur['MAE']:>8.3f}{mcur['RMSE']:>8.3f}{mcur['bias']:>+8.3f}")

    # Multi-window grid optimum (in-sample) per regime.
    print(f"\n  multi-window grid-optimal weights (in-sample MAE):")
    for sub, h2h, name in [(with_df, True, "with H2H"), (without_df, False, "without H2H")]:
        if len(sub) < 10:
            print(f"    {name:<12}: n/a (only {len(sub)} rows)")
            continue
        cols = feature_cols(form_windows, h2h)
        w_opt, mae = grid_search(sub[cols].to_numpy(), sub["actual"].to_numpy(), step)
        print(f"    {name:<12}: {_fmt_w(cols, w_opt)}   (MAE {mae:.3f})")

    # 5-fold CV (out-of-sample): does the multi-window blend actually generalise?
    print(f"\n  5-fold CV MAE — current single-L5 vs multi-window tuned:")
    all_cur, all_opt = [], []
    for sub, h2h, name in [(with_df, True, "with H2H"), (without_df, False, "without H2H")]:
        if len(sub) < 10:
            print(f"    {name:<12}: n/a (only {len(sub)} rows)")
            continue
        cols = feature_cols(form_windows, h2h)
        X = sub[cols].to_numpy()
        cur_e, opt_e = cv_errors(X, sub["actual"].to_numpy(),
                                 current_weights(form_windows, h2h), step)
        all_cur.append(cur_e)
        all_opt.append(opt_e)
        c, o = cur_e.mean(), opt_e.mean()
        tag = "  <- improves" if o < c - 1e-4 else ("  ~ no gain" if abs(o - c) <= 1e-4 else "  (worse)")
        print(f"    {name:<12}: current {c:.3f}   multi-window {o:.3f}{tag}")
    if all_cur:
        c = np.concatenate(all_cur).mean()
        o = np.concatenate(all_opt).mean()
        tag = "  <- improves" if o < c - 1e-4 else ("  ~ no gain" if abs(o - c) <= 1e-4 else "  (worse)")
        print(f"    {'combined':<12}: current {c:.3f}   multi-window {o:.3f}{tag}")

    # Fold-averaged weights (the set to ship) with per-fold spread as a stability check.
    print(f"\n  CV-fold-averaged weights (mean +/- std across folds) -> ship these:")
    for sub, h2h, name in [(with_df, True, "with H2H"), (without_df, False, "without H2H")]:
        if len(sub) < 10:
            continue
        cols = feature_cols(form_windows, h2h)
        mean_w, std_w = fold_optima(sub[cols].to_numpy(), sub["actual"].to_numpy(), step)
        parts = "  ".join(f"{c}={m:.2f}+/-{s:.2f}" for c, m, s in zip(cols, mean_w, std_w))
        print(f"    {name:<12}: {parts}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2024_2026.csv")
    ap.add_argument("--stat", choices=["disposals", "goals"], default="disposals")
    ap.add_argument("--windows", default=",".join(map(str, FORM_WINDOWS)),
                    help="comma-separated form-average windows, e.g. 3,5,10")
    ap.add_argument("--step", type=float, default=0.1,
                    help="grid resolution for the multi-window weight search")
    ap.add_argument("--last-only", action="store_true",
                    help="only each player's final 2026 game (the literal 'predict the last match')")
    ap.add_argument("--both", action="store_true", help="report disposals and goals")
    args = ap.parse_args()

    windows = tuple(int(w) for w in args.windows.split(",") if w.strip())
    df = M.load(args.csv)
    stats = ["disposals", "goals"] if args.both else [args.stat]
    for st in stats:
        report(df, st, windows, args.step, args.last_only)


if __name__ == "__main__":
    main()
