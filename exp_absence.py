"""
Experiment #5 — teammate absences (with/without splits).

When a team's high-usage midfielders are OUT, role and minutes redistribute to
the players who remain — the brainstorm's best "edge vs a slow market" claim, and
the same role/minutes channel that gave experiment #2 its ~8% oracle ceiling.

Backtestable from the CSV alone: every game lists who featured for a team, so we
can reconstruct historical line-ups and build per-player with/without splits, all
leakage-free (target game uses only strictly-earlier games).

Method, walk-forward:
  - A team's "core" each round = its top-K players by season-to-date disposal
    average (a proxy for high-CBA / high-usage personnel), K=8.
  - For target game (player P), n_out = how many of P's *usual* core teammates
    (core players who featured in >=50% of P's prior games this season) are absent
    from this game's line-up. Known pre-game from the named side -> no leakage.
  - From P's prior games, split his stat by "a usual core teammate was missing"
    vs "full core". delta = depleted_mean - full_mean.
  - Adjusted projection = baseline + delta when n_out>=1 and both splits have
    enough sample; delta clipped to a sane range.

We report overall MAE and, crucially, MAE on the subset of games where the
adjustment actually fires (where a real effect would show even if it is washed
out in the full-season average).

    python exp_absence.py            # disposals
    python exp_absence.py --both
"""
import argparse
from collections import defaultdict
import numpy as np
import pandas as pd

import matchup as M

FORM_WINDOWS = M.FORM_WINDOWS
CORE_K = 8


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

    # Line-up per (season, round, team) = set of players who featured.
    lineup = defaultdict(set)
    # Season-to-date disposal sum/count per (season, team, player) -> core ranking.
    dsum = defaultdict(float); dcnt = defaultdict(int)
    for r in df.itertuples(index=False):
        lineup[(r.season, r.round, r.team)].add(r.player)

    # Pre-rank: core set per (season, round, team) from games strictly before round.
    # Build season-to-date averages incrementally per team.
    rows = df.to_dict("records")
    # index games by team in chronological order
    by_team = defaultdict(list)
    for rec in rows:
        by_team[(rec["season"], rec["team"])].append(rec)

    # core_at[(season, round, team)] = set of top-K players by avg disp before round
    core_at = {}
    for (season, team), recs in by_team.items():
        recs.sort(key=lambda r: r["round"])
        psum = defaultdict(float); pcnt = defaultdict(int)
        seen_rounds = sorted({r["round"] for r in recs})
        # snapshot averages as of just-before each round
        for rd in seen_rounds:
            avg = {p: psum[p] / pcnt[p] for p in psum if pcnt[p] >= 2}
            top = sorted(avg, key=avg.get, reverse=True)[:CORE_K]
            core_at[(season, rd, team)] = set(top)
            # now fold in this round's games (becomes "prior" for later rounds)
            for r in recs:
                if r["round"] == rd and pd.notna(r["disposals"]):
                    psum[r["player"]] += r["disposals"]; pcnt[r["player"]] += 1

    phist = defaultdict(list)
    out = []
    for rec in rows:
        key = (rec["player"], rec["team"])
        prior = phist[key]
        sp = [r for r in prior if r["season"] == rec["season"]]
        if len(sp) >= min_prior_season:
            windows = {f"L{w}": float(np.mean([r[stat] for r in sp[-w:]])) for w in FORM_WINDOWS}
            season_avg = float(np.mean([r[stat] for r in sp]))
            has = bool([r for r in prior if r["opponent"] == rec["opponent"]])
            base = M.project(windows, _h2h(prior, rec, stat), season_avg, has)

            # P's usual core teammates: core players (as ranked before each of P's
            # prior games) who appeared in >=50% of P's prior games this season.
            tmate_games = defaultdict(int)
            for r in sp:
                lu = lineup[(r["season"], r["round"], r["team"])]
                cr = core_at.get((r["season"], r["round"], r["team"]), set())
                for p in (lu & cr):
                    if p != rec["player"]:
                        tmate_games[p] += 1
            thresh = max(2, len(sp) // 2)
            usual_core = {p for p, c in tmate_games.items() if c >= thresh}

            # For each prior game, was a usual-core teammate missing? -> split.
            full, depleted = [], []
            for r in sp:
                lu = lineup[(r["season"], r["round"], r["team"])]
                missing = usual_core - lu
                (depleted if missing else full).append(r[stat])

            # Target game: how many usual-core teammates are absent?
            tgt_lu = lineup[(rec["season"], rec["round"], rec["team"])]
            n_out = len(usual_core - tgt_lu)

            adj = base
            fires = False
            if n_out >= 1 and len(depleted) >= 3 and len(full) >= 3:
                delta = float(np.mean(depleted) - np.mean(full))
                delta = float(np.clip(delta, -6, 6))   # guard tiny-sample extremes
                adj = base + delta
                fires = True

            out.append({"baseline": base, "adjusted": adj, "actual": float(rec[stat]),
                        "fires": fires, "n_out": n_out})
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
    ma = metrics(rec["adjusted"], a)
    print(f"\n{'='*66}\n  {stat.upper()}  —  teammate-absence with/without adjustment")
    print(f"  {len(rec)} held-out games (walk-forward, leakage-free)\n{'='*66}")
    print(f"  {'model':<26}{'MAE':>9}{'RMSE':>9}{'bias':>9}")
    print(f"  {'-'*53}")
    print(f"  {'baseline (current blend)':<26}{mb['MAE']:>9.3f}{mb['RMSE']:>9.3f}{mb['bias']:>+9.3f}")
    d = ma['MAE'] - mb['MAE']
    print(f"  {'absence-adjusted':<26}{ma['MAE']:>9.3f}{ma['RMSE']:>9.3f}{ma['bias']:>+9.3f}"
          f"  ({d:+.3f}, {d/mb['MAE']*100:+.1f}%)")
    # The subset where the adjustment actually fires — where any real signal lives.
    fired = rec[rec["fires"]]
    if len(fired):
        fa = fired["actual"].to_numpy()
        fb, ff = metrics(fired["baseline"], fa), metrics(fired["adjusted"], fa)
        d2 = ff['MAE'] - fb['MAE']
        print(f"  {'-'*53}")
        print(f"  adjustment fires on {len(fired)} games ({len(fired)/len(rec)*100:.1f}%):")
        print(f"    baseline {fb['MAE']:.3f}  ->  adjusted {ff['MAE']:.3f}  "
              f"({d2:+.3f}, {d2/fb['MAE']*100:+.1f}%)")


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
