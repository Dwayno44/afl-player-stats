"""
Refresh the per-game stats CSV.

Default (incremental): scrape the *current* season only, append the rows for
any round that isn't already in the CSV, and leave every other row (all prior
seasons and already-captured current-season rounds) exactly as the CSV has it.
The committed CSV is the source of truth for everything except the new round.

    python update_stats.py                 # incremental, current season
    python update_stats.py --full          # re-scrape all seasons from scratch
    python update_stats.py --insecure      # local corporate-SSL workaround

Designed to be cheap to run weekly: historical seasons are never re-scraped.
"""
import argparse

import pandas as pd

import afltables as afl
import matchup as M

CSV_DEFAULT = "games_2022_2026.csv"
HISTORY_START = 2022   # earliest season a full re-scrape rebuilds from
KEY = ["player", "season", "round", "team"]   # uniquely identifies a game row


def merge_new_rounds(old: pd.DataFrame, new: pd.DataFrame,
                     season: int) -> tuple[pd.DataFrame, list[int]]:
    """Append rows from `new` for current-season rounds missing from `old`.

    Prior-season rows and already-present current-season rounds in `old` are
    kept verbatim. Returns (combined, rounds_added).
    """
    old_r = pd.to_numeric(old.loc[old["season"] == season, "round"], errors="coerce")
    have = set(old_r.dropna().astype(int))

    new = new.copy()
    new["round"] = pd.to_numeric(new["round"], errors="coerce")
    new_r = set(new.loc[new["season"] == season, "round"].dropna().astype(int))

    added = sorted(new_r - have)
    if not added:
        return old, []

    add = new[(new["season"] == season) & (new["round"].isin(added))]
    combined = pd.concat([old, add], ignore_index=True)
    combined = combined.drop_duplicates(subset=KEY, keep="last").reset_index(drop=True)
    return combined, added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_DEFAULT)
    ap.add_argument("--season", type=int, default=M.CURRENT_SEASON)
    ap.add_argument("--full", action="store_true",
                    help="re-scrape every season instead of just the new round(s)")
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument("--insecure", action="store_true",
                    help="disable SSL verification (corporate networks)")
    args = ap.parse_args()

    if args.insecure:
        import warnings, requests
        warnings.filterwarnings("ignore")
        afl._get = lambda s, u, retries=3: (
            lambda r: (r.raise_for_status(), r.text)[1]
        )(requests.get(u, verify=False, timeout=30,
                       headers={"User-Agent": "Mozilla/5.0"}))

    if args.full:
        seasons = range(HISTORY_START, args.season + 1)
        print(f"Full re-scrape of {seasons.start}-{seasons.stop - 1} …")
        df = afl.get_game_stats(seasons, teams=None, delay=args.delay)
        df.to_csv(args.csv, index=False)
        print(f"Wrote {len(df)} rows, {df['player'].nunique()} players, "
              f"{df['team'].nunique()} teams to {args.csv}")
        return

    # Incremental: current season only, append missing rounds.
    old = pd.read_csv(args.csv)
    print(f"Loaded {len(old)} existing rows from {args.csv}")
    new = afl.get_game_stats([args.season], teams=None, delay=args.delay)
    combined, added = merge_new_rounds(old, new, args.season)

    if not added:
        print("No new rounds to add — CSV already current.")
        return
    combined.to_csv(args.csv, index=False)
    print(f"Added round(s) {added} for {args.season}: "
          f"{len(combined) - len(old)} new rows -> {len(combined)} total")


if __name__ == "__main__":
    main()
