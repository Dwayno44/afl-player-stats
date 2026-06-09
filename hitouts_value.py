"""
Live hit-out value check: model vs Sportsbet "N+ Hitouts" ladders.

For each upcoming AFL event Sportsbet prices, we project every ruck's hit-outs
(the same season-anchored blend the disposal model uses), estimate the recent-
games sigma, and value each priced rung N as:

    model_p = P(hit_outs >= N) = Phi((proj - N)/sigma)      # Normal, validated conservative
    edge    = model_p * price - 1                            # >0 => +EV by the model

Hit-outs are ruck-only, so we restrict to players whose current-season hit-out
average clears a threshold (captures #1 rucks and ruck-swing backups). The floor-
calibration backtest (hitouts_calib.py) shows the Normal floor is mildly
*conservative* for hit-outs, so edges here are if anything understated.

    python hitouts_value.py                 # all upcoming priced events
    python hitouts_value.py --min-edge 0.05 # only rungs with >=5% edge
    python hitouts_value.py --ruck-min 6    # stricter ruck filter
"""
import argparse
from statistics import NormalDist

import numpy as np
import pandas as pd

import matchup as M
import sportsbet_odds as S

nd = NormalDist()


def ruck_projections(df: pd.DataFrame, team: str, opponent: str,
                     ruck_min: float) -> dict[str, dict]:
    """{player: {proj, sigma, avg, l5}} for current-season players whose hit-out
    average clears `ruck_min` (i.e. genuine rucks)."""
    cur = df[(df.team == team) & (df.season == M.CURRENT_SEASON)]
    vs = df[(df.team == team) & (df.opponent == opponent)]
    out = {}
    for player, g in cur.groupby("player"):
        avg = g["hit_outs"].mean()
        if pd.isna(avg) or avg < ruck_min:
            continue
        forms = M.form_means(g, "hit_outs")
        vg = vs[vs.player == player]
        h2h = M.h2h_weighted(vg, "hit_outs")
        proj = M.project(forms, h2h, avg, len(vg) >= 1)
        recent = M.recent_for_team(df, team, player)["hit_outs"].dropna()
        sigma = float(recent.std(ddof=1)) if len(recent) >= 3 else None
        out[player] = {"proj": proj, "sigma": sigma,
                       "avg": float(avg), "l5": forms.get("L5")}
    return out


def event_value(df, ev, scraper, ruck_min, min_edge, lo_p, hi_p):
    rows = []
    ladder = S.stat_ladder(ev["id"], "hit_outs", scraper)
    if not ladder:
        return None  # markets not posted
    for team, opp in [(ev["home"], ev["away"]), (ev["away"], ev["home"])]:
        projs = ruck_projections(df, team, opp, ruck_min)
        if not projs:
            continue
        joins = S.match_players(list(ladder), list(projs))  # sb_name -> csv_name
        for sb_name, csv_name in joins.items():
            p = projs[csv_name]
            best = S.best_value(ladder[sb_name], p["proj"], p["sigma"],
                                min_edge=min_edge, lo_p=lo_p, hi_p=hi_p)
            allr = S.rung_edges(ladder[sb_name], p["proj"], p["sigma"])
            rows.append({"team": team, "player": csv_name, "proj": p["proj"],
                         "sigma": p["sigma"], "avg": p["avg"], "best": best,
                         "rungs": allr})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    ap.add_argument("--ruck-min", type=float, default=4.0,
                    help="min current-season hit-out average to count as a ruck")
    ap.add_argument("--min-edge", type=float, default=0.0,
                    help="minimum edge for a 'best value' pick (0.05 = 5%)")
    ap.add_argument("--lo-p", type=float, default=S.VALUE_P_LO)
    ap.add_argument("--hi-p", type=float, default=S.VALUE_P_HI)
    args = ap.parse_args()

    df = M.load(args.csv)
    df["hit_outs"] = pd.to_numeric(df["hit_outs"], errors="coerce")
    scraper = S.make_scraper()
    events = S.list_events(scraper)
    print(f"Sportsbet: {len(events)} AFL events\n")

    any_priced = False
    for ev in events:
        rows = event_value(df, ev, scraper, args.ruck_min,
                           args.min_edge, args.lo_p, args.hi_p)
        if rows is None:
            print(f"  {ev['home']} v {ev['away']}: no Hitouts markets yet")
            continue
        if not rows:
            print(f"  {ev['home']} v {ev['away']}: no rucks matched")
            continue
        any_priced = True
        print(f"\n=== {ev['home']} v {ev['away']} ===")
        print(f"  {'player':22s}{'avg':>6}{'proj':>7}{'sig':>6}   best value rung")
        for r in sorted(rows, key=lambda x: -(x["best"]["edge"] if x["best"] else -9)):
            sig = f"{r['sigma']:.1f}" if r["sigma"] else "  -"
            if r["best"]:
                b = r["best"]
                tag = (f"{b['n']}+ @ ${b['price']:.2f}  model {b['model_p']:.0%} "
                       f"vs mkt {b['implied_p']:.0%}  edge {b['edge']:+.1%}")
            else:
                tag = "(no +EV rung in band)"
            print(f"  {r['player']:22s}{r['avg']:>6.1f}{r['proj']:>7.1f}{sig:>6}   {tag}")

    if not any_priced:
        print("\nNo Hitouts markets posted on any event yet.")


if __name__ == "__main__":
    main()
