"""
One-off: does the model find value in Sportsbet's N+ Fantasy Points ladders?

Builds the same projection a disposals card would (season-anchored blend of
L3/L5/L10 + H2H) on the derived `fantasy` column, takes sigma from the player's
recent games, models Fantasy ~ Normal(proj, sigma), and prices every Sportsbet
rung: model_p = P(F >= N) = Phi((proj-N)/sigma), edge = model_p*price - 1.
Reuses sportsbet_odds.best_value (trusted 50-95% band) for the headline pick.

    python fantasy_value.py                       # first live event
    python fantasy_value.py --home Adelaide --away Geelong
"""
import argparse
import re

import matchup as M
import sportsbet_odds as S

FANTASY_MARKET = re.compile(r"^(\d+)\+ Fantasy Points\b", re.I)


def fantasy_ladder(event_id, scraper):
    r = scraper.get(S.EVENT_URL.format(eid=event_id), timeout=30)
    r.raise_for_status()
    out = {}
    for m in r.json().get("marketList", []):
        mt = FANTASY_MARKET.match(m.get("name", ""))
        if not mt:
            continue
        n = int(mt.group(1))
        for sel in m.get("selections", []):
            price = (sel.get("price") or {}).get("winPrice")
            who = sel.get("name")
            if who and price is not None:
                out.setdefault(who, {})[n] = float(price)
    return out


def proj_sigma(df, team):
    """{csv_player: (proj, sigma)} for fantasy, mirroring team_view's inputs."""
    cur = df[(df.team == team) & (df.season == M.CURRENT_SEASON)]
    out = {}
    for player, g in cur.groupby("player"):
        forms = M.form_means(g, "fantasy")
        season = g["fantasy"].mean()
        vg = df[(df.team == team) & (df.player == player)]  # all seasons, any opp filtered below
        out[player] = (forms, season, g)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    ap.add_argument("--home")
    ap.add_argument("--away")
    ap.add_argument("--min-edge", type=float, default=0.05)
    args = ap.parse_args()

    df = M.load(args.csv)
    sc = S.make_scraper()
    events = S.list_events(sc)
    if args.home and args.away:
        ev = S.find_event(args.home, args.away, events=events, scraper=sc)
    else:
        ev = events[0]
    home, away = ev["home"], ev["away"]
    print(f"\n{home} v {away}  (event {ev['id']})\n{'='*64}")

    ladder = fantasy_ladder(ev["id"], sc)
    if not ladder:
        print("No N+ Fantasy Points markets posted yet.")
        return

    picks = []
    for team, opp in [(home, away), (away, home)]:
        cur = df[(df.team == team) & (df.season == M.CURRENT_SEASON)]
        names_csv = list(cur["player"].unique())
        name_map = S.match_players(list(ladder), names_csv)  # sb -> csv
        for sb_name, csv_name in name_map.items():
            g = cur[cur.player == csv_name]
            forms = M.form_means(g, "fantasy")
            season = g["fantasy"].mean()
            vg = df[(df.team == team) & (df.player == csv_name) & (df.opponent == opp)]
            h2h = M.h2h_weighted(vg, "fantasy")
            has = len(vg) >= 1
            proj = M.project(forms, h2h, season, has)
            recent = M.recent_for_team(df, team, csv_name)["fantasy"].dropna()
            if len(recent) < 3:
                continue
            sigma = float(recent.std(ddof=1))
            best = S.best_value(ladder[sb_name], proj, sigma, min_edge=args.min_edge)
            if best:
                picks.append((best["edge"], csv_name, team, proj, sigma, best))

    picks.sort(reverse=True)
    print(f"{'player':22s}{'team':>4} {'proj':>6} {'sig':>5}  best rung (model% / mkt% / edge)")
    print("-" * 78)
    for edge, name, team, proj, sigma, b in picks:
        print(f"{name:22s}{team[:4]:>4} {proj:6.1f} {sigma:5.1f}  "
              f"{b['n']}+ @ ${b['price']:.2f}  "
              f"{round(b['model_p']*100):>3}% / {round(b['implied_p']*100):>3}% / +{round(b['edge']*100)}%")
    print(f"\n{len(picks)} value picks at >= {args.min_edge:.0%} edge (50-95% model band).")


if __name__ == "__main__":
    main()
