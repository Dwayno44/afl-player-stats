"""
AFL Tables scraper  —  afltables.com
=====================================
Provides player and season statistics for the AFL via scraping.

Usage (CLI):
    python3 afltables.py players 2026            # all players + season totals
    python3 afltables.py player "Marcus Bontempelli" --season 2026
    python3 afltables.py team Collingwood --season 2026
    python3 afltables.py season 2026 --out stats_2026.csv

Requires:
    pip install cloudscraper beautifulsoup4 lxml pandas
"""

from __future__ import annotations

import re
import sys
import csv
import json
import time
import logging
import argparse
import io
from typing import Optional

import cloudscraper
import pandas as pd
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

BASE       = "https://afltables.com/afl"
STATS_BASE = f"{BASE}/stats/"
SEAS_BASE  = f"{BASE}/seas/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.8",
    "Referer": "https://afltables.com/",
}

# Season column abbreviations → readable names
SEASON_COL_MAP = {
    "Yr":  "year",
    "Team": "team",
    "#":   "jumper",
    "GM":  "games",
    "GL":  "goals",
    "BH":  "behinds",
    "KI":  "kicks",
    "HB":  "handballs",
    "DI":  "disposals",
    "MK":  "marks",
    "TK":  "tackles",
    "HO":  "hit_outs",
    "FR":  "frees_for",
    "FA":  "frees_against",
    "I5":  "inside_50s",
    "CL":  "clearances",
    "RB":  "rebound_50s",
    "CP":  "contested_possessions",
    "UP":  "uncontested_possessions",
    "CM":  "contested_marks",
    "MI":  "marks_inside_50",
    "1%":  "one_percenters",
    "BO":  "bounces",
    "GA":  "goal_assist",
    "TO":  "time_on_ground_pct",
    "BR":  "brownlow_votes",
    "SC":  "supercoach",
    "AF":  "afl_fantasy",
}

# Game-log column abbreviations (same page, per-game tables)
GAME_COL_MAP = {
    "Opponent": "opponent",
    "Rnd":      "round",
    "Result":   "result",
    "#":        "jumper",
    "GL":       "goals",
    "BH":       "behinds",
    "KI":       "kicks",
    "HB":       "handballs",
    "DI":       "disposals",
    "MK":       "marks",
    "TK":       "tackles",
    "HO":       "hit_outs",
    "FR":       "frees_for",
    "FA":       "frees_against",
    "I5":       "inside_50s",
    "CL":       "clearances",
    "RB":       "rebound_50s",
    "CP":       "contested_possessions",
    "UP":       "uncontested_possessions",
    "CM":       "contested_marks",
    "MI":       "marks_inside_50",
    "1%":       "one_percenters",
    "BO":       "bounces",
    "GA":       "goal_assist",
    "TO":       "time_on_ground_pct",
    "BR":       "brownlow_votes",
    "SC":       "supercoach",
    "AF":       "afl_fantasy",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("afltables")


# ── Session ───────────────────────────────────────────────────────────────────

def _make_session() -> cloudscraper.CloudScraper:
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def _get(session: cloudscraper.CloudScraper, url: str, retries: int = 3) -> str:
    """Fetch a page with retry on transient errors."""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning(f"Attempt {attempt} failed ({e}); retrying in {wait}s …")
            time.sleep(wait)
    raise RuntimeError("unreachable")


# ── Player index ──────────────────────────────────────────────────────────────

def get_season_player_list(season: int,
                           session: Optional[cloudscraper.CloudScraper] = None
                           ) -> list[dict]:
    """
    Returns every player who appeared in `season` with their profile URL.
    Fields: name, url
    """
    s    = session or _make_session()
    url  = f"{STATS_BASE}{season}.html"
    html = _get(s, url)
    soup = BeautifulSoup(html, "lxml")

    players = []
    for table in soup.find_all("table", class_="sortable"):
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            link_tag = cols[1].find("a")
            if not link_tag:
                continue
            href = link_tag.get("href", "")
            raw_name = href.split("/")[-1].replace(".html", "")
            raw_name = re.sub(r"\d+$", "", raw_name)
            name = raw_name.replace("_", " ")
            players.append({
                "name": name,
                "url": STATS_BASE + href,
            })
    return players


# ── Player profile ────────────────────────────────────────────────────────────

def _normalise_cols(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    df = df.copy()
    df.columns = [col_map.get(str(c).strip(), str(c).strip().lower().replace(" ", "_"))
                  for c in df.columns]
    return df


def get_player_season_stats(player_url: str,
                             season: Optional[int] = None,
                             session: Optional[cloudscraper.CloudScraper] = None
                             ) -> dict:
    """
    Fetches a player's profile page and returns:
      {
        "meta":    {"name": ..., "born": ..., "debut": ..., "height": ..., "weight": ...},
        "totals":  DataFrame  — one row per season (career totals),
        "averages":DataFrame  — one row per season (career averages),
        "games":   DataFrame  — one row per game  (entire career, or filtered by season),
      }
    """
    s    = session or _make_session()
    html = _get(s, player_url)
    soup = BeautifulSoup(html, "lxml")

    meta: dict[str, object] = {"url": player_url}
    for b in soup.find_all("b"):
        label = b.get_text(strip=True).rstrip(":")
        sibling = b.next_sibling
        val = sibling.strip() if sibling and isinstance(sibling, str) else ""
        if label in ("Born", "Debut", "Height", "Weight", "Position"):
            meta[label.lower()] = val
    h1 = soup.find("h1")
    if h1:
        meta["name"] = h1.get_text(strip=True)

    all_tables = pd.read_html(io.StringIO(html))
    totals_df   = _normalise_cols(all_tables[0], SEASON_COL_MAP) if len(all_tables) > 0 else pd.DataFrame()
    averages_df = _normalise_cols(all_tables[1], SEASON_COL_MAP) if len(all_tables) > 1 else pd.DataFrame()

    if season and "year" in totals_df.columns:
        totals_df   = totals_df[totals_df["year"].astype(str).str.contains(str(season))]
        averages_df = averages_df[averages_df["year"].astype(str).str.contains(str(season))]

    season_pattern = str(season) if season else r"\d{4}"
    game_dfs = pd.read_html(io.StringIO(html), match=re.compile(rf"[A-Za-z ]+\s*-\s*{season_pattern}"))

    game_rows: list[pd.DataFrame] = []
    for gdf in game_dfs:
        gdf = _normalise_cols(gdf, GAME_COL_MAP)
        if "round" in gdf.columns:
            gdf = gdf[~gdf["round"].astype(str).str.lower().isin(["rnd", "nan", ""])]
        game_rows.append(gdf)

    games_df = pd.concat(game_rows, ignore_index=True) if game_rows else pd.DataFrame()

    return {
        "meta":     meta,
        "totals":   totals_df.reset_index(drop=True),
        "averages": averages_df.reset_index(drop=True),
        "games":    games_df.reset_index(drop=True),
    }


def find_player_url(name: str,
                    session: Optional[cloudscraper.CloudScraper] = None) -> str:
    """
    Resolve a player name to their AFL Tables profile URL.
    AFL Tables slugs are in Last_First order (e.g. Bontempelli_Marcus).
    """
    s = session or _make_session()
    parts = name.strip().split()
    if len(parts) < 2:
        raise ValueError(f"Need full name 'First Last', got: {name!r}")
    first = "_".join(parts[:-1])
    last  = parts[-1]
    last_initial = last[0].upper()
    idx_url = f"{STATS_BASE}players{last_initial}_idx.html"
    html = _get(s, idx_url)
    soup = BeautifulSoup(html, "lxml")

    slug     = f"{last}_{first}"
    pattern  = re.compile(rf"players/{last_initial}/{re.escape(slug)}", re.I)
    link = soup.find("a", href=pattern)
    if not link:
        slug2    = f"{first}_{last}"
        pattern2 = re.compile(rf"players/{last_initial[0]}/{re.escape(slug2)}", re.I)
        link = soup.find("a", href=pattern2)
    if not link:
        raise LookupError(
            f"Player {name!r} not found. "
            f"Browse https://afltables.com/afl/stats/players{last_initial}_idx.html"
        )
    return STATS_BASE + link["href"]


# ── Season-level bulk stats ───────────────────────────────────────────────────

def get_season_stats(season: int,
                     session: Optional[cloudscraper.CloudScraper] = None
                     ) -> pd.DataFrame:
    """
    Fetches the season stats index page and returns a DataFrame with one row
    per player — season totals for all players who appeared in `season`.
    """
    s    = session or _make_session()
    url  = f"{STATS_BASE}{season}.html"
    log.info(f"Fetching season {season} stats index: {url}")
    html = _get(s, url)

    dfs = pd.read_html(io.StringIO(html), attrs={"class": "sortable"})
    if not dfs:
        raise ValueError(f"No sortable tables found on {url}")

    df = dfs[0]
    df = _normalise_cols(df, SEASON_COL_MAP)

    if "games" in df.columns:
        df = df[pd.to_numeric(df["games"], errors="coerce").notna()].copy()

    soup = BeautifulSoup(html, "lxml")
    names, urls = [], []
    for table in soup.find_all("table", class_="sortable"):
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            link = cols[1].find("a")
            if link:
                href = link.get("href", "")
                raw  = href.split("/")[-1].replace(".html", "")
                raw  = re.sub(r"\d+$", "", raw)
                names.append(raw.replace("_", " "))
                urls.append(STATS_BASE + href)
            else:
                names.append("")
                urls.append("")

    if len(names) == len(df):
        df.insert(0, "player_url", urls)
        df.insert(0, "player",     names)

    return df


# ── Team season page ──────────────────────────────────────────────────────────

def get_team_season_stats(team: str, season: int,
                           session: Optional[cloudscraper.CloudScraper] = None
                           ) -> pd.DataFrame:
    """
    Fetches the team-season page and returns player totals for that team/year.
    """
    s = session or _make_session()
    slug = team.lower().replace(" ", "_")
    url  = f"{BASE}/teams/{slug}/{season}.html"
    log.info(f"Fetching team page: {url}")
    html = _get(s, url)
    dfs  = pd.read_html(io.StringIO(html), attrs={"class": "sortable"})
    if not dfs:
        raise ValueError(f"No stats table on {url}")
    df = pd.concat(dfs, ignore_index=True)
    df.insert(0, "team",   team)
    df.insert(0, "season", season)
    return df


# ── Output helpers ────────────────────────────────────────────────────────────

def df_to_csv_str(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def df_to_records(df: pd.DataFrame) -> list[dict]:
    return df.where(pd.notna(df), None).to_dict(orient="records")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_table(df: pd.DataFrame, max_rows: int = 20) -> None:
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", max_rows)
    print(df.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AFL Tables scraper — fetch 2026 player stats"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_players = sub.add_parser("players", help="All players in a season")
    p_players.add_argument("season", type=int)
    p_players.add_argument("--out", help="Output CSV path")
    p_players.add_argument("--json", action="store_true")

    p_player = sub.add_parser("player", help="Individual player stats")
    p_player.add_argument("name")
    p_player.add_argument("--season", type=int, default=None)
    p_player.add_argument("--games",  action="store_true")
    p_player.add_argument("--out",    help="Output CSV path")

    p_team = sub.add_parser("team", help="Team season player stats")
    p_team.add_argument("name")
    p_team.add_argument("--season", type=int, default=2026)
    p_team.add_argument("--out",    help="Output CSV path")

    p_season = sub.add_parser("season", help="Full season stats (all players)")
    p_season.add_argument("year", type=int)
    p_season.add_argument("--out",  help="Output CSV path")
    p_season.add_argument("--json", action="store_true")

    args = parser.parse_args()
    session = _make_session()

    try:
        if args.cmd == "players":
            print(f"Fetching player list for {args.season} …")
            players = get_season_player_list(args.season, session)
            print(f"Found {len(players)} players")
            for p in players[:10]:
                print(f"  {p['name']:<30} {p['url']}")
            if len(players) > 10:
                print(f"  … and {len(players) - 10} more")

        elif args.cmd == "player":
            print(f"Looking up {args.name!r} …")
            url  = find_player_url(args.name, session)
            data = get_player_season_stats(url, season=args.season, session=session)
            print(f"\nBio: {data['meta']}")
            print(f"\nSeason totals ({len(data['totals'])} row(s)):")
            _print_table(data["totals"])
            if args.games and not data["games"].empty:
                print(f"\nGame log ({len(data['games'])} game(s)):")
                _print_table(data["games"], max_rows=50)
            elif args.games:
                print("\nNo game-by-game data found for that season filter.")
            if args.out:
                df = data["games"] if args.games else data["totals"]
                df.to_csv(args.out, index=False)
                print(f"\nSaved to {args.out}")

        elif args.cmd == "team":
            print(f"Fetching {args.name} {args.season} …")
            df = get_team_season_stats(args.name, args.season, session)
            _print_table(df)
            if args.out:
                df.to_csv(args.out, index=False)
                print(f"\nSaved to {args.out}")

        elif args.cmd == "season":
            print(f"Fetching all player stats for {args.year} …")
            df = get_season_stats(args.year, session)
            print(f"{len(df)} players found")
            _print_table(df)
            if args.out:
                df.to_csv(args.out, index=False)
                print(f"\nSaved to {args.out}")
            if args.json:
                print(json.dumps(df_to_records(df), indent=2)[:2000])

    except LookupError as e:
        print(f"Not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
