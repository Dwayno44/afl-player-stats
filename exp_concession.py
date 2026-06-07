"""
Experiment #4 — opponent concession (defence-vs-average) instead of the noisy
1-3 game head-to-head term.

The live model blends a recency-weighted H2H average (weight 0.10 with-H2H) built
from a player's own 1-3 prior meetings with tonight's opponent — a tiny, noisy
sample. The brainstorm's claim: "what this opponent concedes to players like X"
(full-season samples) is a more stable signal. We test that here.

Concession metric (leakage-free, defence-vs-average):
  For every prior game, a player's expectation = their season-to-date average
  (prior games only). actual/expected is how much that opponent let them beat
  their norm. An opponent's concession ratio = mean of those ratios over the
  games it has conceded so far this season (fallback: all prior seasons). >1 means
  the opponent gives up more than players' baselines; <1 means it suppresses.

We compare, walk-forward on the same held-out games:
  baseline   : current blend (incl. its H2H term)               [the live model]
  team-conc  : baseline projection x opponent team concession ratio
  role-conc  : baseline projection x opponent concession ratio within the
               target player's role bucket (role proxied from the box score)

Roles are proxied without CBA data: a player's prior-games profile of
contested%/clearances/rebound50s/marks-inside-50 buckets them into
inside-mid / outside / half-back / forward / ruck / key-back.

    python exp_concession.py            # disposals
    python exp_concession.py --both
"""
import argparse
import numpy as np
import pandas as pd

import matchup as M

CURRENT_SEASON = M.CURRENT_SEASON
FORM_WINDOWS = M.FORM_WINDOWS


def _h2h(prior, tgt, col):
    g = [r for r in prior if r["opponent"] == tgt["opponent"]]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in g], float)
    v = np.array([r[col] for r in g], float)
    return float((v * w).sum() / w.sum())


def role_of(prior_rows) -> str:
    """Cheap role bucket from a player's prior box-score profile (no CBA needed)."""
    def avg(k):
        vs = [r.get(k) for r in prior_rows if pd.notna(r.get(k))]
        return float(np.mean(vs)) if vs else 0.0
    ho, cl = avg("hit_outs"), avg("clearances")
    cp, ucp = avg("contested_possessions"), avg("uncontested_possessions")
    reb, mi5, mks = avg("rebound_50s"), avg("marks_inside_50"), avg("marks")
    disp = avg("disposals")
    if ho >= 8:
        return "ruck"
    if cl >= 3.5 and cp >= 9:
        return "inside_mid"
    if mi5 >= 1.2 or (avg("goals") >= 0.8 and disp < 14):
        return "forward"
    if reb >= 2.5 or (mks >= 4 and ucp >= 9 and disp >= 15):
        return "half_back"
    if disp >= 18 and ucp >= cp:
        return "outside_mid"
    if disp < 11:
        return "key_back"
    return "other"


def collect(df: pd.DataFrame, stat: str, min_prior_season: int = 3) -> pd.DataFrame:
    """Walk-forward records with baseline, team-concession and role-concession
    projections, plus the actual. Concession ratios use only games strictly
    earlier than each target (global chronological order)."""
    df = df[df[stat].notna()].copy()
    # Global chronological index so concession accumulates without leakage.
    df = df.sort_values(["season", "round"]).reset_index(drop=True)
    rows_all = df.to_dict("records")

    # Per-player history (for the player's own projection inputs + role).
    from collections import defaultdict
    phist = defaultdict(list)            # (player,team) -> prior records
    # Opponent concession accumulators, separated by season for recency.
    # opp -> season -> list[ratio]; opp -> season -> role -> list[ratio]
    team_acc = defaultdict(lambda: defaultdict(list))
    role_acc = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    league_acc = []                      # all ratios seen so far (de-bias anchor)

    def conc_ratio(acc_for_opp, season):
        """Opponent concession RELATIVE to the league: mean(opp ratios) /
        mean(all ratios so far). Centering on the running league mean removes the
        upward ratio bias, so a neutral defence sits at ~1.0. This season if it has
        samples, else pooled across prior seasons. 1.0 (neutral) if unseen."""
        cur = acc_for_opp.get(season, [])
        if len(cur) >= 5:
            opp_mean = float(np.mean(cur))
        else:
            pool = [x for s, lst in acc_for_opp.items() if s <= season for x in lst]
            if len(pool) < 5:
                return 1.0
            opp_mean = float(np.mean(pool))
        lg = float(np.mean(league_acc)) if len(league_acc) >= 50 else 1.0
        return opp_mean / lg if lg > 0 else 1.0

    out = []
    for rec in rows_all:
        key = (rec["player"], rec["team"])
        prior = phist[key]
        sp = [r for r in prior if r["season"] == rec["season"]]
        opp, season = rec["opponent"], rec["season"]

        if len(sp) >= min_prior_season:
            windows = {f"L{w}": float(np.mean([r[stat] for r in sp[-w:]])) for w in FORM_WINDOWS}
            season_avg = float(np.mean([r[stat] for r in sp]))
            has = bool([r for r in prior if r["opponent"] == opp])
            base = M.project(windows, _h2h(prior, rec, stat), season_avg, has)
            # Same blend but with the H2H term removed (form + season only).
            no_h2h = M.project(windows, np.nan, season_avg, False)

            role = role_of(prior)
            t_ratio = conc_ratio(team_acc[opp], season)
            r_ratio = conc_ratio(role_acc[opp][role], season)
            # Clip so a thin/extreme sample can't blow the projection up.
            clip = lambda x: float(np.clip(x, 0.80, 1.25))
            out.append({
                "baseline": base,                       # current model (with H2H)
                "no_h2h": no_h2h,                        # drop H2H entirely
                "team_conc": base * clip(t_ratio),      # concession on top of H2H
                "role_conc": base * clip(r_ratio),
                "noh2h_team_conc": no_h2h * clip(t_ratio),   # concession REPLACES H2H
                "noh2h_role_conc": no_h2h * clip(r_ratio),
                "actual": float(rec[stat]),
                "role": role,
            })

        # --- update accumulators AFTER using them (post-game = now "prior") ---
        # Expected for this game = player's season-to-date avg (prior games only).
        if len(sp) >= 2:
            exp = float(np.mean([r[stat] for r in sp]))
            if exp > 0:
                ratio = float(rec[stat]) / exp
                team_acc[opp][season].append(ratio)
                role_acc[opp][role_of(prior)][season].append(ratio)
                league_acc.append(ratio)
        phist[key].append(rec)

    return pd.DataFrame(out)


def metrics(pred, actual) -> dict:
    err = np.asarray(pred) - np.asarray(actual)
    return {"MAE": float(np.mean(np.abs(err))), "RMSE": float(np.sqrt(np.mean(err ** 2))),
            "bias": float(np.mean(err))}


def report(df, stat):
    rec = collect(df, stat)
    a = rec["actual"].to_numpy()
    mb = metrics(rec["baseline"], a)
    print(f"\n{'='*70}\n  {stat.upper()}  —  H2H baseline vs opponent concession")
    print(f"  {len(rec)} held-out games (walk-forward, leakage-free)\n{'='*70}")
    print(f"  {'model':<30}{'MAE':>9}{'RMSE':>9}{'bias':>9}")
    print(f"  {'-'*57}")
    for name, col in [("baseline (current, with H2H)", "baseline"),
                      ("no H2H (form+season only)", "no_h2h"),
                      ("H2H x team concession", "team_conc"),
                      ("H2H x role concession", "role_conc"),
                      ("no-H2H x team concession", "noh2h_team_conc"),
                      ("no-H2H x role concession", "noh2h_role_conc")]:
        m = metrics(rec[col], a)
        d = m['MAE'] - mb['MAE']
        tag = "" if col == "baseline" else f"  ({d:+.3f}, {d/mb['MAE']*100:+.1f}%)"
        print(f"  {name:<30}{m['MAE']:>9.3f}{m['RMSE']:>9.3f}{m['bias']:>+9.3f}{tag}")


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
