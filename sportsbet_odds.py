"""
Sportsbet AFL player-disposal odds (the Same Game Multi "N+ Disposals" ladder).

Unlike The Odds API -- which for AFL only exposes a single disposals Over/Under
line per player -- Sportsbet prices every integer milestone (10+, 11+, ... 40+
disposals) separately. That ladder is exactly what our model wants: our floor is
"clears N at conf%", so for each priced rung N we can compare the bookie's implied
probability (1/price) against the model's P(disposals >= N) and flag value.

Source: Sportsbet's own JSON API (no key, no quota), via cloudscraper to clear the
Akamai bot check (same approach afltables.py already uses for Cloudflare). NOTE:
Sportsbet geo-restricts to AU -- this will not work from a non-AU IP (e.g. GitHub
CI runners), so the page build keeps odds opt-in (matchup_app --odds).

Endpoints (class 50 "Australian Rules", competition 4165 "AFL"):
  Events list : /apigw/sportsbook-sports/Sportsbook/Sports/Competitions/4165/Events
  One event   : /apigw/sportsbook-sports/Sportsbook/Sports/Events/{eventId}
                -> {'marketList': [{'name': '<N>+ Disposals',
                                    'selections': [{'name': player,
                                                    'price': {'winPrice': decimal}}]}]}

NAME JOINS reuse lineups.py's normaliser. Teams: Sportsbet decorates club names
("Adelaide Crows", "Gold Coast SUNS", "GWS GIANTS"); SB2CSV maps them to the
afltables spellings the CSV/fixture use. Players: Sportsbet gives "Given Surname",
the CSV stores "Surname, Given"; we match on a normalised "given surname" form,
which copes with multi-word surnames (Ah Chee, Neal-Bullen, O'Sullivan) because
the CSV explicitly delimits the surname.

CLI:
    python sportsbet_odds.py events
    python sportsbet_odds.py ladder --event 10527412
    python sportsbet_odds.py ladder --home Adelaide --away Geelong
"""
import argparse
import re
import sys
from statistics import NormalDist

import cloudscraper

from lineups import _norm, _strip_mid

AFL_COMP = 4165   # Sportsbet "AFL" competition id (class 50). May change by season.
EVENTS_URL = ("https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/"
              "Sports/Competitions/{comp}/Events")
EVENT_URL = ("https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/"
             "Sports/Events/{eid}")

# Sportsbet participant name (normalised, lowercased) -> afltables/CSV club name.
SB2CSV = {
    "adelaide crows": "Adelaide",
    "brisbane lions": "Brisbane Lions",
    "carlton": "Carlton",
    "collingwood": "Collingwood",
    "essendon": "Essendon",
    "fremantle": "Fremantle",
    "geelong cats": "Geelong",
    "gold coast suns": "Gold Coast",
    "gws giants": "Greater Western Sydney",
    "greater western sydney giants": "Greater Western Sydney",
    "hawthorn": "Hawthorn",
    "melbourne": "Melbourne",
    "north melbourne": "North Melbourne",
    "port adelaide": "Port Adelaide",
    "richmond": "Richmond",
    "st kilda": "St Kilda",
    "sydney swans": "Sydney",
    "west coast eagles": "West Coast",
    "western bulldogs": "Western Bulldogs",
}

# Sportsbet labels each N+ player-prop family by stat. Map our CSV column name to
# the word Sportsbet uses in the market title ("12+ Hitouts", "4+ Tackles", ...).
STAT_MARKET_LABEL = {
    "disposals": "Disposals",
    "fantasy": "Fantasy Points",
    "goals": "Goal",
    "hit_outs": "Hitouts",
    "tackles": "Tackles",
    "clearances": "Clearances",
    "marks": "Marks",
    "kicks": "Kicks",
    "handballs": "Handballs",
}


def _market_re(stat: str) -> re.Pattern:
    """Regex matching this stat's 'N+ <Label>' market titles, capturing N."""
    if stat == "goals":
        # Sportsbet labels these "1+ Goal" / "2+ Goals" (singular at 1). Anchor the
        # end so we don't grab "2+ Goals Combined" / "2+ Goals Every Quarter".
        return re.compile(r"^(\d+)\+ Goals?$", re.I)
    label = STAT_MARKET_LABEL.get(stat, stat.title())
    return re.compile(rf"^(\d+)\+ {re.escape(label)}\b", re.I)


_DISPOSAL_MARKET = _market_re("disposals")   # back-compat alias


def make_scraper():
    return cloudscraper.create_scraper(browser={"custom": "Chrome"})


def _team_to_csv(name: str) -> str | None:
    return SB2CSV.get(_norm(name))


def list_events(scraper=None) -> list[dict]:
    """Upcoming AFL events from Sportsbet, mapped to CSV club names.

    Returns [{id, start (unix int), home, away, home_raw, away_raw}], skipping
    placeholder/futures rows (empty participants) and any club we can't map.
    """
    scraper = scraper or make_scraper()
    r = scraper.get(EVENTS_URL.format(comp=AFL_COMP), timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json():
        p1, p2 = e.get("participant1", ""), e.get("participant2", "")
        if not p1 or not p2:
            continue   # futures / placeholder market
        home, away = _team_to_csv(p1), _team_to_csv(p2)
        if not home or not away:
            continue
        out.append({"id": e["id"], "start": e.get("startTime"),
                    "home": home, "away": away, "home_raw": p1, "away_raw": p2})
    return out


def find_event(home: str, away: str, date_str: str | None = None,
               events: list[dict] | None = None, scraper=None) -> dict | None:
    """Find the Sportsbet event for a fixture game by unordered CSV team pair.

    Team order can differ between our fixture and Sportsbet, so we match the
    set {home, away}. If the pair plays twice in the window (rare), `date_str`
    (YYYY-MM-DD...) breaks the tie by nearest start time.
    """
    events = events if events is not None else list_events(scraper)
    want = {home, away}
    cands = [e for e in events if {e["home"], e["away"]} == want]
    if not cands:
        return None
    if len(cands) == 1 or not date_str:
        return cands[0]
    try:
        from datetime import datetime, timezone
        target = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        return min(cands, key=lambda e: abs((e.get("start") or 0) - target))
    except ValueError:
        return cands[0]


def stat_ladder(event_id: int, stat: str = "disposals",
                scraper=None) -> dict[str, dict[int, float]]:
    """{player_name: {threshold: decimal_price}} from the event's "N+ <Stat>"
    markets. Player names are Sportsbet's raw "Given Surname" strings."""
    scraper = scraper or make_scraper()
    r = scraper.get(EVENT_URL.format(eid=event_id), timeout=30)
    r.raise_for_status()
    rx = _market_re(stat)
    ladder: dict[str, dict[int, float]] = {}
    for m in r.json().get("marketList", []):
        mt = rx.match(m.get("name", ""))
        if not mt:
            continue
        n = int(mt.group(1))
        for sel in m.get("selections", []):
            price = (sel.get("price") or {}).get("winPrice")
            who = sel.get("name")
            if who and price is not None:
                ladder.setdefault(who, {})[n] = float(price)
    return ladder


def disposal_ladder(event_id: int, scraper=None) -> dict[str, dict[int, float]]:
    """Back-compat: the disposals ladder (see stat_ladder)."""
    return stat_ladder(event_id, "disposals", scraper)


def match_players(sb_names, csv_names) -> dict[str, str]:
    """Map Sportsbet "Given Surname" -> CSV "Surname, Given".

    Exact match on a normalised "given surname" form first, then a fallback that
    matches a shared surname plus a given-name prefix (Will/William, Tom/Thomas).
    """
    cands = []   # (given_norm, surname_norm, "given surname", original_csv)
    for orig in csv_names:
        sur, _, giv = orig.partition(", ")
        gn, sn = _norm(_strip_mid(giv)), _norm(sur)
        cands.append((gn, sn, f"{gn} {sn}".strip(), orig))

    out = {}
    for sb in sb_names:
        key = _norm(sb)
        hit = next((c[3] for c in cands if c[2] == key), None)
        if hit is None:
            # fallback: ends with the surname, given-prefix agrees
            for gn, sn, _full, orig in cands:
                if sn and key.endswith(" " + sn):
                    pre = key[: -len(sn) - 1]
                    if pre and gn and min(len(pre), len(gn)) >= 3 and (pre.startswith(gn) or gn.startswith(pre)):
                        hit = orig
                        break
        if hit is not None:
            out[sb] = hit
    return out


def rung_edges(player_ladder: dict[int, float], proj: float, sigma: float | None) -> list[dict]:
    """For one player's ladder, value each rung against the model.

    Disposals are modelled Normal(proj, sigma) -- the same assumption behind the
    disposal floor (floor = proj - z*sigma => P(>=floor) = conf). So for rung N:
      model_p  = P(disposals >= N) = Phi((proj - N)/sigma)
      implied  = 1 / price            (book's no-vig-free implied probability)
      edge     = model_p * price - 1  (>0 => +EV by the model)
    Returns rungs sorted by descending edge. Empty if sigma is unusable (<=0/None)
    or proj missing -- without a spread we can't put a probability on a milestone.
    """
    if proj is None or sigma is None or sigma <= 0:
        return []
    nd = NormalDist()
    rows = []
    for n, price in sorted(player_ladder.items()):
        model_p = nd.cdf((proj - n) / sigma)
        rows.append({
            "n": n, "price": round(price, 2),
            "model_p": round(model_p, 4),
            "implied_p": round(1.0 / price, 4),
            "edge": round(model_p * price - 1.0, 4),
        })
    rows.sort(key=lambda r: r["edge"], reverse=True)
    return rows


# Only trust the model near the middle of the distribution. A Normal approximation
# is unreliable in the tails, where a tiny absolute probability error times a big
# price manufactures a fake "edge" (e.g. model 3% vs implied 2% on a $41 longshot).
# Backable value lives where the bet is both probable and still priced -- restrict
# the "best pick" to rungs the model puts at 50-95%, matching the project's stance
# of backing high-confidence floors as short-priced singles.
VALUE_P_LO = 0.50
VALUE_P_HI = 0.95


def best_value(player_ladder, proj, sigma, min_edge: float = 0.0,
               lo_p: float = VALUE_P_LO, hi_p: float = VALUE_P_HI):
    """Highest-edge rung within the trusted probability band, or None.

    Considers only rungs the model rates between `lo_p` and `hi_p` (so we don't
    surface tail longshots), and requires the edge to clear `min_edge`."""
    band = [e for e in rung_edges(player_ladder, proj, sigma)
            if lo_p <= e["model_p"] <= hi_p]
    if not band:
        return None
    top = max(band, key=lambda e: e["edge"])
    return top if top["edge"] >= min_edge else None


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_events(_args, scraper):
    from datetime import datetime, timezone
    evs = list_events(scraper)
    for e in evs:
        t = datetime.fromtimestamp(e["start"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if e["start"] else "?"
        print(f"{e['id']}  {t}Z  {e['home']} v {e['away']}")
    print(f"\n{len(evs)} events.")
    return 0


def _cmd_ladder(args, scraper):
    eid = args.event
    if not eid:
        if not (args.home and args.away):
            print("error: pass --event ID, or both --home and --away", file=sys.stderr)
            return 2
        ev = find_event(args.home, args.away, args.date, scraper=scraper)
        if not ev:
            print(f"error: no Sportsbet event for {args.home} v {args.away}", file=sys.stderr)
            return 1
        eid = ev["id"]
        print(f"{args.home} v {args.away} -> event {eid}\n")

    ladder = stat_ladder(eid, args.stat, scraper)
    if not ladder:
        print(f"No 'N+ {STAT_MARKET_LABEL.get(args.stat, args.stat.title())}' markets "
              "on this event (props may not be posted yet).")
        return 0
    for player in sorted(ladder):
        rungs = sorted(ladder[player])
        print(f"{player:<24} " + "  ".join(f"{n}+@{ladder[player][n]}" for n in rungs))
    print(f"\n{len(ladder)} players priced.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Sportsbet AFL disposal-ladder odds.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("events", help="list upcoming AFL events").set_defaults(func=_cmd_events)
    pl = sub.add_parser("ladder", help="disposal ladder for one event")
    pl.add_argument("--event", type=int, help="Sportsbet event id")
    pl.add_argument("--home", help="home team (CSV name) -- with --away, finds the event")
    pl.add_argument("--away", help="away team (CSV name)")
    pl.add_argument("--date", help="YYYY-MM-DD to disambiguate double-ups")
    pl.add_argument("--stat", default="disposals", choices=list(STAT_MARKET_LABEL),
                    help="which N+ player-prop ladder to fetch")
    pl.set_defaults(func=_cmd_ladder)
    args = p.parse_args(argv)

    scraper = make_scraper()
    try:
        return args.func(args, scraper)
    except Exception as e:  # network / parse / bot-block
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
