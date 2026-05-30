"""
Home-state enrichment for per-game stats.

afltables stat rows carry no venue, so we pull each game's venue and designated
home/away side from the Squiggle API and join them onto the stats frame.

JOIN KEY -- why not (season, round, team):
  afltables and Squiggle disagree on round numbering. afltables counts the AFL's
  pre-season "Opening Round" as Round 1 (so its Round 2 == Squiggle's Round 1),
  while Squiggle calls Opening Round "Round 0". Joining on round number therefore
  shifts most games by one and silently assigns the wrong venue. Instead we match
  each club's games chronologically by OPPONENT, which is convention-independent
  and also captures finals (where Squiggle uses letter labels like "QF"). A club
  meets a given opponent at most a few times per season, so opponent order
  (earlier round -> earlier meeting) disambiguates repeats.

The signal we care about is whether a player's team played in its OWN home state,
which is NOT the same as the designated home/away flag:
  - Geelong is often the "away" team but still plays at the M.C.G. in Victoria.
  - Hawthorn / North Melbourne sell "home" games to Tasmania (York Park, TAS), so
    they are the home team but out of their home state.
So `at_home_state` (venue state == team's home state) better reflects travel and
ground familiarity than the raw home/away designation.
"""
from collections import defaultdict, deque

import pandas as pd

# Each club's home state.
TEAM_STATE = {
    "Adelaide": "SA", "Port Adelaide": "SA",
    "Brisbane Lions": "QLD", "Gold Coast": "QLD",
    "Carlton": "VIC", "Collingwood": "VIC", "Essendon": "VIC", "Geelong": "VIC",
    "Hawthorn": "VIC", "Melbourne": "VIC", "North Melbourne": "VIC",
    "Richmond": "VIC", "St Kilda": "VIC", "Western Bulldogs": "VIC",
    "Greater Western Sydney": "NSW", "Sydney": "NSW",
    "Fremantle": "WA", "West Coast": "WA",
}

# Every venue used 2024-2026 (Squiggle spellings) -> state.
VENUE_STATE = {
    "M.C.G.": "VIC", "Docklands": "VIC", "Kardinia Park": "VIC", "Eureka Stadium": "VIC",
    "Adelaide Oval": "SA", "Norwood Oval": "SA", "Barossa Park": "SA", "Adelaide Hills": "SA",
    "Perth Stadium": "WA", "Hands Oval": "WA",
    "S.C.G.": "NSW", "Sydney Showground": "NSW",
    "Gabba": "QLD", "Carrara": "QLD",
    "York Park": "TAS", "Bellerive Oval": "TAS",
    "Manuka Oval": "ACT",
    "Marrara Oval": "NT", "Traeger Park": "NT",
}


def game_lookup(years, verify: bool = False) -> dict:
    """{(season, team): [ {opponent, venue, venue_state, is_home}, ... ]} with one
    entry per game for each club, in chronological order (Squiggle returns games
    sorted by round then date). Both clubs in every game get an entry."""
    import fixtures as F
    lut: dict[tuple, list] = defaultdict(list)
    for yr in years:
        for g in F.get_fixtures(int(yr), remaining_only=False, verify=verify):
            venue = g["venue"]
            vs = VENUE_STATE.get(venue)
            home, away = g["home"], g["away"]
            lut[(int(yr), home)].append(
                {"opponent": away, "venue": venue, "venue_state": vs, "is_home": True})
            lut[(int(yr), away)].append(
                {"opponent": home, "venue": venue, "venue_state": vs, "is_home": False})
    return dict(lut)


def _row_lut(df: pd.DataFrame, verify: bool = False) -> dict:
    """Build {(season, team, round): info} by matching each club's distinct CSV
    games to its Squiggle games chronologically, keyed on opponent."""
    years = sorted(df["season"].dropna().astype(int).unique())
    games = game_lookup(years, verify=verify)

    distinct = df[["season", "team", "round", "opponent"]].drop_duplicates()
    distinct = distinct.assign(_r=pd.to_numeric(distinct["round"], errors="coerce"))

    row_lut: dict = {}
    for (season, team), grp in distinct.groupby(["season", "team"]):
        # Squiggle games for this club, bucketed by opponent in chronological order.
        by_opp: dict = defaultdict(deque)
        for info in games.get((int(season), team), []):
            by_opp[info["opponent"]].append(info)
        # CSV games in round order; pop the earliest unused meeting per opponent.
        for _, row in grp.sort_values("_r").iterrows():
            q = by_opp.get(row["opponent"])
            info = q.popleft() if q else None
            row_lut[(int(season), team, row["round"])] = info
    return row_lut


def enrich(df: pd.DataFrame, verify: bool = False) -> pd.DataFrame:
    """Add venue, venue_state, is_home and at_home_state columns to a stats frame.

    Rows that don't join (e.g. an opponent Squiggle lacks, or an unmapped venue)
    get NaN location fields and at_home_state = NA."""
    out = df.copy()
    row_lut = _row_lut(out, verify=verify)

    venue, vstate, ishome = [], [], []
    for season, r, team in zip(out["season"], out["round"], out["team"]):
        info = row_lut.get((int(season), team, r))
        if info:
            venue.append(info["venue"])
            vstate.append(info["venue_state"])
            ishome.append(info["is_home"])
        else:
            venue.append(None)
            vstate.append(None)
            ishome.append(None)

    out["venue"] = venue
    out["venue_state"] = vstate
    out["is_home"] = ishome
    team_state = out["team"].map(TEAM_STATE)
    ahs = (out["venue_state"] == team_state).astype("boolean")
    ahs[out["venue_state"].isna()] = pd.NA
    out["at_home_state"] = ahs
    return out


def coverage(df: pd.DataFrame) -> dict:
    """Quick diagnostics on how many rows were successfully located."""
    n = len(df)
    located = int(df["venue_state"].notna().sum())
    return {
        "rows": n,
        "located": located,
        "located_pct": round(100 * located / n, 1) if n else 0.0,
        "at_home_state": int((df["at_home_state"] == True).sum()),
        "interstate": int((df["at_home_state"] == False).sum()),
    }
