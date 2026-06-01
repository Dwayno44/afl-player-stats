"""
AFL named-team (lineup) pull from the official AFL API (Champion Data backed).

Lets the matchup page filter to players actually NAMED in the team, instead of
every player with current-season history (which wrongly includes dropped,
injured, managed and retired players).

Teams are named ~Thursday 6:20pm AEST for the round. Before that the roster
endpoint carries no players and we simply have no lineup for those teams -- the
caller then falls back to showing all current-season players and flags the team
as "not yet named". This module never guesses a lineup.

Request flow (all reachable through the corporate proxy with verify=False):
  1. POST  api.afl.com.au/cfs/afl/WMCTok                         -> {"token": ...}
  2. GET   aflapi.afl.com.au/afl/v2/competitions/1/compseasons   -> {year} season id
  3. GET   aflapi.afl.com.au/afl/v2/matches?compSeasonId&roundNumber -> providerIds
  4. GET   api.afl.com.au/cfs/afl/matchRoster/full/{providerId}  -> teamPlayers

The token is passed in the `x-media-mis-token` header. Emergencies (position
"EMERG") are excluded -- they aren't in the playing team unless promoted late.

NAME JOIN -- the AFL API gives givenName/surname; afltables (our CSV) stores
"Surname, Given". We normalise both (strip accents, unify apostrophes, drop a
trailing middle initial, lowercase) and match on surname + given, with a
prefix fallback for nickname/long-form differences (Will/William, Tom/Thomas).
Validated against round 12 2026: every named player that has 2026 CSV data
matched; the only misses were players with zero 2026 games (returning/injured/
debut), who the page never displays anyway.

TEAM NAMES -- the AFL API decorates club names ("Geelong Cats", "Sydney Swans");
AFL2CSV maps them back to the afltables spellings used in the stats CSV.
"""
import re
import unicodedata

import requests
import urllib3

# verify=False is needed behind the corporate SSL-intercepting proxy; mute the
# per-request InsecureRequestWarning so a page build doesn't spew one per call.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WMCTOK = "https://api.afl.com.au/cfs/afl/WMCTok"
COMPSEASONS = "https://aflapi.afl.com.au/afl/v2/competitions/1/compseasons"
MATCHES = "https://aflapi.afl.com.au/afl/v2/matches"
ROSTER = "https://api.afl.com.au/cfs/afl/matchRoster/full/{}"
UA = "afl-player-stats matchup tool (github.com/Dwayno44/afl-player-stats)"

# AFL API club name -> afltables/CSV name. Clubs not listed already match.
AFL2CSV = {
    "Adelaide Crows": "Adelaide",
    "GWS GIANTS": "Greater Western Sydney",
    "Geelong Cats": "Geelong",
    "Gold Coast SUNS": "Gold Coast",
    "Sydney Swans": "Sydney",
    "West Coast Eagles": "West Coast",
}

# Module-level caches so a multi-round page build hits the network minimally.
_token_cache: str | None = None
_cid_cache: dict[int, int] = {}


def _get(url: str, token: str | None, verify: bool):
    headers = {"User-Agent": UA}
    if token:
        headers["x-media-mis-token"] = token
    r = requests.get(url, headers=headers, timeout=30, verify=verify)
    r.raise_for_status()
    return r.json()


def get_token(verify: bool = False) -> str:
    """POST for a short-lived AFL API token (cached for the process)."""
    global _token_cache
    if _token_cache is None:
        r = requests.post(WMCTOK, headers={"User-Agent": UA}, timeout=30, verify=verify)
        r.raise_for_status()
        _token_cache = r.json()["token"]
    return _token_cache


def compseason_id(year: int, token: str, verify: bool = False) -> int | None:
    """Resolve the men's Premiership compSeason id for a calendar year."""
    if year in _cid_cache:
        return _cid_cache[year]
    js = _get(COMPSEASONS, token, verify)
    for cs in js.get("compSeasons", []):
        name = cs.get("name", "")
        if name.startswith(str(year)) and "Premiership" in name and "Women" not in name:
            _cid_cache[year] = cs["id"]
            return cs["id"]
    return None


def _matches(cid: int, round_number: int, token: str, verify: bool) -> list[dict]:
    url = f"{MATCHES}?compSeasonId={cid}&roundNumber={round_number}&pageSize=30"
    return _get(url, token, verify).get("matches", [])


def _norm(s: str) -> str:
    """Lowercase, strip accents, unify curly apostrophes for name comparison."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("’", "'").strip().lower()


def _strip_mid(given: str) -> str:
    """Drop a trailing middle initial, e.g. 'Bailey J.' -> 'Bailey'."""
    return re.sub(r"\s+[A-Za-z]\.$", "", given or "")


def _split_csv(name: str) -> tuple[str, str, str]:
    """'Surname, Given' -> (surname_norm, given_norm, original)."""
    sur, _, giv = name.partition(", ")
    return _norm(sur), _norm(_strip_mid(giv)), name


def _match(cands: list[tuple[str, str, str]], surname: str, given: str) -> str | None:
    """Find the CSV player-name string for an API (surname, given). Exact on the
    normalised surname+given first, then a prefix fallback within the surname so
    Will/William, Tom/Thomas, Chris/Christopher still join."""
    s, g = _norm(surname), _norm(_strip_mid(given))
    for cs, cg, orig in cands:
        if cs == s and cg == g:
            return orig
    for cs, cg, orig in cands:
        if cs == s and min(len(cg), len(g)) >= 3 and (cg.startswith(g) or g.startswith(cg)):
            return orig
    return None


def named_players(df, year: int, round_number: int, verify: bool = False) -> dict[str, set]:
    """{csv_team: {exact CSV player-name strings named to play}} for the given
    round. Only teams with a posted lineup appear; teams not yet named are
    omitted so the caller can fall back to showing everyone. Emergencies excluded.

    `df` supplies the per-team roster of current-season players to join against.
    Any network/parse failure raises -- the caller decides how to degrade.
    """
    token = get_token(verify)
    cid = compseason_id(year, token, verify)
    if cid is None:
        return {}

    cur = df[df["season"] == year]
    csv_idx: dict[str, list] = {
        team: [_split_csv(p) for p in grp["player"].unique()]
        for team, grp in cur.groupby("team")
    }

    out: dict[str, set] = {}
    for m in _matches(cid, round_number, token, verify):
        try:
            jr = _get(ROSTER.format(m["providerId"]), token, verify)
        except requests.HTTPError:
            continue
        if "teamPlayers" not in jr or "match" not in jr:
            continue  # not named yet
        sides = jr["teamPlayers"]
        for side, key in ((sides[0], "homeTeam"), (sides[1], "awayTeam")):
            players = side.get("players", [])
            if not players:
                continue  # this side not named yet
            team = jr["match"][key]["name"]
            team = AFL2CSV.get(team, team)
            cands = csv_idx.get(team, [])
            named = set()
            for p in players:
                pl = p["player"]
                if pl.get("position") == "EMERG":
                    continue
                pn = pl["player"]["playerName"]
                hit = _match(cands, pn["surname"], pn["givenName"])
                if hit:
                    named.add(hit)
            out[team] = named  # team is named even if few join our 2026 data
    return out
