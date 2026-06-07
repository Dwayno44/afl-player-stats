"""
Spike probe: does the AFL (Champion Data) API expose historical per-game
CBA% and TOG? Reuses the token flow from lineups.py. Read-only discovery —
prints status codes and the stat field names it finds, fetches nothing in bulk.
"""
import json
import sys
import requests
import lineups as L

UA = L.UA


def getj(url, token, verify):
    h = {"User-Agent": UA, "x-media-mis-token": token}
    r = requests.get(url, headers=h, timeout=30, verify=verify)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)


def main():
    # 1) token + compseason on THIS machine. Try verify=True first (no proxy now).
    verify = True
    try:
        token = L.get_token(verify=True)
        print("token OK (verify=True)")
    except Exception as e:
        print("verify=True failed:", repr(e)[:160], "\n-> retrying verify=False")
        verify = False
        token = L.get_token(verify=False)
        print("token OK (verify=False)")

    year = 2025  # a complete season -> stable historical data to mine
    cid = L.compseason_id(year, token, verify)
    print(f"compSeason {year} id = {cid}")

    matches = L._matches(cid, 1, token, verify)
    print(f"round 1 {year}: {len(matches)} matches")
    if not matches:
        sys.exit("no matches — stop")
    m = matches[0]
    pid = m.get("providerId")
    print("sample match providerId:", pid, "| match keys:", list(m.keys())[:12])

    # 2) probe candidate per-match player-stats endpoints.
    cands = [
        f"https://api.afl.com.au/cfs/afl/playerStats/match/{pid}",
        f"https://api.afl.com.au/cfs/afl/matchPlayerStats/{pid}",
        f"https://api.afl.com.au/cfs/afl/statsCentre/players/match/{pid}",
        f"https://api.afl.com.au/cfs/afl/statsCentre/match/{pid}",
        f"https://aflapi.afl.com.au/afl/v2/matches/{pid}/stats",
        f"https://aflapi.afl.com.au/afl/v2/matches/{pid}/player-statistics",
        f"https://aflapi.afl.com.au/afl/v2/matches/{pid}/playerstatistics",
        f"https://aflapi.afl.com.au/afl/v2/matches/{pid}",
        f"https://api.afl.com.au/cfs/afl/playerStats/{pid}/advanced",
        f"https://api.afl.com.au/statspro/afl/v1/matches/{pid}/playerStats",
    ]
    hit = None
    for url in cands:
        try:
            sc, js = getj(url, token, verify)
        except Exception as e:
            print(f"  [ERR] {url}\n        {repr(e)[:120]}")
            continue
        n = len(js) if isinstance(js, (list, dict)) else 0
        print(f"  [{sc}] {url}  (json {'dict' if isinstance(js, dict) else type(js).__name__}, top-len {n})")
        if sc == 200 and js:
            hit = (url, js)

    if not hit:
        print("\nno stats endpoint found among candidates.")
        return
    url, js = hit
    print(f"\nHIT: {url}\ntop-level keys:", list(js.keys()) if isinstance(js, dict) else f"list[{len(js)}]")
    # Dig for anything that looks like CBA / time-on-ground.
    blob = json.dumps(js)[:4000]
    for needle in ["entr", "Entr", "bounce", "Bounce", "CBA", "cba",
                   "timeOnGround", "TimeOnGround", "tog", "TOG", "percentPlayed"]:
        if needle in blob:
            print(f"  found token in payload: '{needle}'")
    print("\n--- first 1500 chars of payload ---")
    print(blob[:1500])


if __name__ == "__main__":
    main()
