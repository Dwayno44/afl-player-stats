"""
AFL fixture pull from the public Squiggle API (https://api.squiggle.com.au).

Squiggle's team names already match afltables (e.g. "Brisbane Lions",
"Greater Western Sydney", "Western Bulldogs"), so fixtures join directly to the
per-game stats CSV with no name mapping.

Usage:
    python fixtures.py 2026                 # remaining games, grouped by round
    python fixtures.py 2026 --all           # include completed games too
    python fixtures.py 2026 --round 13
"""
import argparse
import requests

API = "https://api.squiggle.com.au/"
# Squiggle etiquette: identify the app in the User-Agent.
UA = "afl-player-stats matchup tool (github.com/Dwayno44/afl-player-stats)"


def get_fixtures(year: int, remaining_only: bool = True, verify: bool = True) -> list[dict]:
    """
    Returns a list of fixture dicts sorted by (round, date):
        {round, date, venue, home, away, complete}
    `complete` is Squiggle's 0..100 progress (100 = finished).
    `remaining_only` drops games that have already completed.
    `verify=False` works around corporate SSL interception.
    """
    r = requests.get(f"{API}?q=games;year={year}",
                     headers={"User-Agent": UA}, timeout=30, verify=verify)
    r.raise_for_status()
    games = r.json().get("games", [])

    out = []
    for g in games:
        if g.get("hteam") is None or g.get("ateam") is None:
            continue  # bye / placeholder
        complete = g.get("complete", 0) or 0
        if remaining_only and complete >= 100:
            continue
        out.append({
            "round": g.get("round"),
            "date": g.get("date"),
            "venue": g.get("venue"),
            "home": g.get("hteam"),
            "away": g.get("ateam"),
            "complete": complete,
        })
    out.sort(key=lambda x: (x["round"] if x["round"] is not None else 99,
                            x["date"] or ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int, nargs="?", default=2026)
    ap.add_argument("--all", action="store_true", help="include completed games")
    ap.add_argument("--round", type=int, default=None, help="filter to one round")
    ap.add_argument("--insecure", action="store_true",
                    help="disable SSL verification (corporate networks)")
    args = ap.parse_args()

    fx = get_fixtures(args.year, remaining_only=not args.all, verify=not args.insecure)
    if args.round is not None:
        fx = [g for g in fx if g["round"] == args.round]

    cur = None
    for g in fx:
        if g["round"] != cur:
            cur = g["round"]
            print(f"\n-- Round {cur} --")
        flag = "" if g["complete"] >= 100 else "  (upcoming)"
        print(f"  {g['date']}  {g['home']:>22}  v  {g['away']:<22}  @ {g['venue']}{flag}")
    print(f"\n{len(fx)} games")


if __name__ == "__main__":
    main()
