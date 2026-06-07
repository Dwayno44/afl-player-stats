"""
Spike fetcher: pull per-player per-match CBA / TOG / disposals / fantasy from the
AFL (Champion Data) API into a tidy frame, so we can backtest whether CBA adds
signal beyond the box score the CSV already has.

Endpoint (discovered in probe_cba.py):
  GET cfs/afl/playerStats/match/{matchId} -> {homeTeamPlayerStats, awayTeamPlayerStats}
  each node: playerStats.stats.{disposals,dreamTeamPoints,clearances.centreClearances,...},
             playerStats.timeOnGroundPercentage,
             playerStats.stats.extendedStats.{centreBounceAttendances,ruckContests,kickins}

Self-contained: we take disposals + dreamTeamPoints straight from the API, so the
backtest needs no join to the afltables CSV. Raw match JSON is cached to disk so
reruns are free and we hit the network once.

    python fetch_cba.py --years 2025,2026 --out cba_games.csv
"""
import argparse
import json
import os
import time

import pandas as pd
import requests

import lineups as L

CACHE = "cba_cache"
PSTATS = "https://api.afl.com.au/cfs/afl/playerStats/match/{}"


def _match_json(pid, token, verify):
    """Cached GET of one match's player stats."""
    path = os.path.join(CACHE, f"{pid}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    h = {"User-Agent": L.UA, "x-media-mis-token": token}
    r = requests.get(PSTATS.format(pid), headers=h, timeout=30, verify=verify)
    if r.status_code != 200:
        return None
    js = r.json()
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(js, f)
    time.sleep(0.12)   # be polite
    return js


def _rows_for_side(side, team, opponent, season, rnd, team_cb_max):
    out = []
    for p in side:
        ps = p["playerStats"]
        st = ps.get("stats") or {}
        ext = st.get("extendedStats") or {}
        nm = p["player"]["player"]["player"]["playerName"]
        cba = ext.get("centreBounceAttendances")
        out.append({
            "season": season, "round": rnd, "team": team, "opponent": opponent,
            "player": f"{nm['surname']}, {nm['givenName']}",
            "disposals": st.get("disposals"),
            "fantasy": st.get("dreamTeamPoints"),
            "pct_played": ps.get("timeOnGroundPercentage"),
            "cba": cba,
            "cba_pct": (100.0 * cba / team_cb_max) if (cba is not None and team_cb_max) else None,
            "centre_clearances": (st.get("clearances") or {}).get("centreClearances"),
            "ruck_contests": ext.get("ruckContests"),
            "kickins": ext.get("kickins"),
        })
    return out


def fetch_year(year, token, verify):
    cid = L.compseason_id(year, token, verify)
    if cid is None:
        print(f"  {year}: no compseason"); return []
    rows = []
    for rnd in range(1, 30):                     # H&A + finals; empty rounds end it
        matches = L._matches(cid, rnd, token, verify)
        if not matches:
            if rnd > 24:
                break
            continue
        got = 0
        for m in matches:
            js = _match_json(m["providerId"], token, verify)
            # Unplayed matches return the keys with null values -> skip those too.
            if not js or not js.get("homeTeamPlayerStats") or not js.get("awayTeamPlayerStats"):
                continue
            home = L.AFL2CSV.get(m["home"]["team"]["name"], m["home"]["team"]["name"])
            away = L.AFL2CSV.get(m["away"]["team"]["name"], m["away"]["team"]["name"])
            hmax = max((((p["playerStats"].get("stats") or {}).get("extendedStats") or {})
                        .get("centreBounceAttendances") or 0) for p in js["homeTeamPlayerStats"])
            amax = max((((p["playerStats"].get("stats") or {}).get("extendedStats") or {})
                        .get("centreBounceAttendances") or 0) for p in js["awayTeamPlayerStats"])
            rows += _rows_for_side(js["homeTeamPlayerStats"], home, away, year, rnd, hmax)
            rows += _rows_for_side(js["awayTeamPlayerStats"], away, home, year, rnd, amax)
            got += 1
        print(f"  {year} R{rnd}: {got} matches")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2025,2026")
    ap.add_argument("--out", default="cba_games.csv")
    args = ap.parse_args()
    verify = True
    try:
        token = L.get_token(verify=True)
    except Exception:
        verify = False
        token = L.get_token(verify=False)
    rows = []
    for y in (int(x) for x in args.years.split(",")):
        print(f"year {y}:")
        rows += fetch_year(y, token, verify)
    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    cov = df["cba"].notna().mean() * 100
    print(f"\nwrote {args.out}: {len(df)} player-games, {df['player'].nunique()} players, "
          f"CBA non-null {cov:.1f}%")


if __name__ == "__main__":
    main()
