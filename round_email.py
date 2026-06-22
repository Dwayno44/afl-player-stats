"""
Build a round-bet email from the built page (docs/index.html).

Reads the embedded DATA so the picks match exactly what's shown on the site, then
shapes the upcoming games into a punter-facing slate (the default `--format slate`)
built around how people actually bet -- a result to chase at three grains:

  THE GAME PLAYS   - one same-game multi per match (up to 4 legs), balanced across
                     the two teams so most legs are opposing. Opposing legs trade
                     off (negatively correlated) so the real same-game-multi slip
                     prices LONGER than the fair product; same-team legs correlate
                     and price SHORTER. Each play is flagged with that direction.
  THE DAY MULTIS   - the best leg from each game on a day, combined across games.
                     Cross-game => independent => the slip should match the product.
  THE WEEKEND SWING- the best legs across the round into one big-payout multi.

Monday games (AWST) are excluded by default (--include-monday to keep them); games
that have already started are dropped. Player edges are GREEN (>= 5%) / AMBER (0-5%),
computed with the same floor + EV maths the page uses:
  disposal floor = floor(proj - z*sigma), priced at that exact rung;
  fantasy        = the best-edge ladder rung AT OR BELOW the floor (coarse 5-step
                   ladder), model ~ Normal(proj, sigma); edge = model_p*price - 1.

The older cumulative-tier view is still available via `--format tiers`.

    python round_email.py                      # slate text + writes round_email.html
    python round_email.py --include-monday
    python round_email.py --format tiers       # legacy three-tier view
    python round_email.py --html-only
"""
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

CONF = 0.85                      # matches the page default (M.DEFAULT_CONF)
Z = NormalDist().inv_cdf(CONF)
GREEN, AMBER = 0.05, 0.0         # edge thresholds (VAL_CLEAR / val-border)
GOAL_CONF = 0.65                 # credible anytime scorer: P(>=1 goal) >= this (matches the page)
GOAL_NUM_MIN = 2.0               # only suggest a goal count when proj >= this; below it, imply 1
GOALS_PER_GAME = 3
MAX_GAMEPLAY_LEGS = 4            # legs in a per-game same-game multi
SWING_TARGET = 8                # target legs for the round-wide Weekend Swing
FILL_MIN = 0.03                 # an amber leg needs >= this edge to fill a Game Play
_ND = NormalDist()
_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_games(path: str) -> tuple[list[dict], str]:
    html = Path(path).read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA\s*=\s*(\{.*?\});", html, re.S).group(1))
    gen = (re.search(r"generated ([0-9-]+)", html) or [None, "?"])[1]
    return data["games"], gen


def fmt_awst(g: dict) -> str:
    if g.get("unixtime"):
        d = datetime.fromtimestamp(g["unixtime"] + 8 * 3600, tz=timezone.utc)
        h = d.hour % 12 or 12
        ap = "am" if d.hour < 12 else "pm"
        return f"{_DOW[d.weekday()]} {d.day} {_MON[d.month-1]}, {h}:{d.minute:02d}{ap} AWST"
    return (g.get("date") or "")[:16]


def _disp_leg(r: dict):
    proj, sig, lad = r.get("D_proj"), r.get("D_sigma"), r.get("od_ladder")
    if proj is None or not sig or not lad:
        return None
    floor = max(0, math.floor(proj - Z * sig))
    price = lad.get(str(floor))
    if price is None:
        return None
    mp = _ND.cdf((proj - floor) / sig)
    return {"market": "disposals", "n": floor, "unit": "disposals",
            "price": price, "mp": mp, "edge": mp * price - 1}


def _fan_leg(r: dict):
    proj, sig, lad = r.get("F_proj"), r.get("F_sigma"), r.get("od_ladder_F")
    if proj is None or not sig or not lad:
        return None
    floor = max(0, math.floor(proj - Z * sig))
    best = None
    for k, price in lad.items():
        n = int(k)
        if n > floor:                       # never above the floor (see page logic)
            continue
        mp = _ND.cdf((proj - n) / sig)
        edge = mp * price - 1
        if best is None or edge > best["edge"]:
            best = {"market": "fantasy", "n": n, "unit": "fantasy",
                    "price": price, "mp": mp, "edge": edge}
    return best


def game_picks(g: dict) -> dict:
    """{'t1': [...], 't2_add': [...], 'goals': [...]} of bet dicts for one game."""
    greens, ambers = {}, {}     # (team, player) -> best leg
    goals = []
    for team, opp, side in [(g["home"], g["away"], g["home_view"]),
                            (g["away"], g["home"], g["away_view"])]:
        for r in side:
            key = (team, r["player"])
            for leg in (_disp_leg(r), _fan_leg(r)):
                if leg is None:
                    continue
                leg = {**leg, "player": r["player"], "team": team, "opp": opp}
                if leg["edge"] >= GREEN:
                    if key not in greens or leg["price"] > greens[key]["price"]:
                        greens[key] = leg
                elif leg["edge"] >= AMBER:
                    if key not in ambers or leg["price"] > ambers[key]["price"]:
                        ambers[key] = leg
            gp = r.get("G_proj")
            if gp is not None:
                p1 = 1 - math.exp(-gp)              # model anytime: P(>=1 goal)
                if p1 >= GOAL_CONF:                 # credible scorer
                    n = math.floor(gp) if gp >= GOAL_NUM_MIN else 1
                    price = (r.get("od_ladder_G") or {}).get(str(n))
                    goals.append({"player": r["player"], "team": team, "proj": gp,
                                  "p1": p1, "n": n, "price": price})
    t2_add = [v for k, v in ambers.items() if k not in greens]
    goals = sorted(goals, key=lambda x: -x["p1"])[:GOALS_PER_GAME]   # highest anytime % first
    by_edge = lambda L: sorted(L, key=lambda x: -x["edge"])
    return {"t1": by_edge(greens.values()), "t2_add": by_edge(t2_add), "goals": goals}


def _multi(bets: list[dict]) -> tuple[float, int, int]:
    """(combined decimal odds, priced legs, unpriced legs) for a naive multi.
    The product of leg prices is the *fair* combined price; Sportsbet's actual
    same-game multi differs (legs are correlated and the book adjusts the price)."""
    odds, priced, missing = 1.0, 0, 0
    for b in bets:
        p = b.get("price")
        if p:
            odds *= p
            priced += 1
        else:
            missing += 1
    return odds, priced, missing


def multis(p: dict) -> dict:
    """Cumulative-tier multi odds: T1, T1+T2, T1+T2+T3 (goals)."""
    t1 = list(p["t1"])
    t2 = t1 + list(p["t2_add"])
    t3 = t2 + list(p["goals"])
    return {"t1": _multi(t1), "t2": _multi(t2), "t3": _multi(t3)}


# ── slate construction (Game Plays / Day Multis / Weekend Swing) ───────────────

def _upcoming(games, include_monday=False, now=None):
    """Remaining games that have odds and haven't started. Monday games (AWST)
    are dropped by default, matching the no-Monday multi rule."""
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    out = []
    for g in games:
        if not any("od_ladder" in r for r in g["home_view"] + g["away_view"]):
            continue
        u = g.get("unixtime")
        if u and u < now:                       # already started
            continue
        if u and not include_monday:
            if datetime.fromtimestamp(u + 8 * 3600, tz=timezone.utc).weekday() == 0:
                continue                        # Monday AWST
        out.append(g)
    return out


def _game_id(b) -> frozenset:
    """Identify a leg's match by its (team, opponent) pair, order-independent."""
    return frozenset((b["team"], b["opp"]))


def best_leg(g):
    """Highest-edge priced GREEN for a game, or None."""
    greens = [b for b in game_picks(g)["t1"] if b.get("price")]
    return max(greens, key=lambda x: x["edge"]) if greens else None


def correlation_note(h: int, a: int) -> str:
    """Net same-game-multi price direction from the home/away leg split. Cross-team
    pairs trade off (longer slip); same-team pairs move together (shorter slip)."""
    cross = h * a
    same = h * (h - 1) // 2 + a * (a - 1) // 2
    if cross > same:
        return "slip should read LONGER than fair (opposing legs trade off)"
    if same > cross:
        return "slip should read SHORTER than fair (same-team legs move together)"
    return "slip should read about fair (mixed correlation)"


def game_play(g, max_legs=MAX_GAMEPLAY_LEGS, fill_min=FILL_MIN):
    """One same-game multi for a game: up to max_legs priced legs, balanced across
    the two teams (greens first, then value-supported ambers). None if too thin."""
    p = game_picks(g)
    pool = [b for b in (list(p["t1"]) + [a for a in p["t2_add"] if a["edge"] >= fill_min])
            if b.get("price")]
    if len(pool) < 2:
        return None
    home, away = g["home"], g["away"]
    cap = (max_legs + 1) // 2                    # 2 per team when max_legs == 4
    by_team = {home: [], away: []}
    for b in sorted(pool, key=lambda x: -x["edge"]):
        by_team.setdefault(b["team"], []).append(b)
    chosen = by_team.get(home, [])[:cap] + by_team.get(away, [])[:cap]
    if len(chosen) < max_legs:                   # one side thin: fill from the rest
        rest = [b for b in sorted(pool, key=lambda x: -x["edge"]) if b not in chosen]
        chosen += rest[:max_legs - len(chosen)]
    chosen = sorted(chosen[:max_legs], key=lambda x: -x["edge"])
    h = sum(1 for b in chosen if b["team"] == home)
    return {"legs": chosen, "fair": _multi(chosen), "h": h, "a": len(chosen) - h,
            "note": correlation_note(h, len(chosen) - h)}


def day_multis(games):
    """Per-day cross-game multi: the best leg from each game on a day. Only days
    with >= 2 games (a single-game day is already covered by its Game Play)."""
    days, order = {}, []
    for g in games:
        u = g.get("unixtime")
        if u:
            d = datetime.fromtimestamp(u + 8 * 3600, tz=timezone.utc)
            key, label = d.strftime("%Y-%m-%d"), _DOW[d.weekday()]
        else:
            key, label = (g.get("date") or "")[:10], ""
        if key not in days:
            days[key] = {"label": label, "games": []}
            order.append(key)
        days[key]["games"].append(g)
    out = []
    for key in order:
        gs = days[key]["games"]
        if len(gs) < 2:
            continue
        legs = [b for b in (best_leg(g) for g in gs) if b]
        if len(legs) >= 2:
            out.append({"day": days[key]["label"] or key, "legs": legs, "fair": _multi(legs)})
    return out


def weekend_swing(games, target=SWING_TARGET):
    """Round-wide cross-game multi: best leg per game, then the next-best greens by
    edge until `target` legs. Flags same-game pairs (they correlate)."""
    chosen = [b for b in (best_leg(g) for g in games) if b]
    if len(chosen) < target:
        extras = []
        for g in games:
            greens = sorted([b for b in game_picks(g)["t1"] if b.get("price")],
                            key=lambda x: -x["edge"])
            extras += greens[1:]                 # skip each game's best (already in)
        for b in sorted(extras, key=lambda x: -x["edge"]):
            if len(chosen) >= target:
                break
            chosen.append(b)
    seen, pairs = {}, []
    for b in chosen:
        seen.setdefault(_game_id(b), []).append(b["player"].split(",")[0])
    for names in seen.values():
        if len(names) > 1:
            pairs.append(" + ".join(names))
    return {"legs": chosen, "fair": _multi(chosen), "pairs": pairs}


# ── rendering ─────────────────────────────────────────────────────────────────

def _leg_txt(b):
    return (f"{b['player']} ({b['team'][:3].strip()}) — {b['n']}+ {b['unit']} @ ${b['price']:.2f}"
            f"  [model {round(b['mp']*100)}%, +{round(b['edge']*100)}%]")


def _goal_txt(b):
    line = f"{b['n']}+ goals" if b["proj"] >= GOAL_NUM_MIN else "anytime goal (1+)"
    odds = f" @ ${b['price']:.2f}" if b.get("price") else " @ n/a"
    return f"{b['player']} ({b['team'][:3].strip()}) — {line}{odds}  [{round(b['p1']*100)}% anytime, proj {b['proj']:.1f}]"


def render_text(games, gen) -> str:
    out = [f"PuntersMate — round bet summary (page generated {gen})", "=" * 60]
    all_t1, all_t2, all_t3 = [], [], []
    for g in games:
        if not any("od_ladder" in r for r in g["home_view"] + g["away_view"]):
            continue
        p = game_picks(g)
        if not (p["t1"] or p["t2_add"] or p["goals"]):
            continue
        all_t1 += list(p["t1"])
        all_t2 += list(p["t1"]) + list(p["t2_add"])
        all_t3 += list(p["t1"]) + list(p["t2_add"]) + list(p["goals"])
        out.append(f"\n{g['home']} v {g['away']}  ·  R{g['round']} · {fmt_awst(g)} · {g.get('venue','')}")
        out.append("  TIER 1 — highest confidence (greens):")
        out += [f"    • {_leg_txt(b)}" for b in p["t1"]] or ["    (none)"]
        out.append("  TIER 2 — mid confidence (tier 1 + ambers):")
        out += [f"    • {_leg_txt(b)}" for b in p["t2_add"]] or ["    (no new amber picks)"]
        out.append("  TIER 3 — lowest confidence (tier 2 + goal scorers):")
        out += [f"    • {_goal_txt(b)}" for b in p["goals"]] or ["    (no credible goal scorers)"]
        m = multis(p)
        def mline(label, t):
            odds, n, miss = t
            extra = f", {miss} unpriced" if miss else ""
            return f"    {label}: ${odds:,.2f}  ({n} legs{extra})"
        out.append("  COMBINED MULTI (fair price = product of legs):")
        out.append(mline("Tier 1", m["t1"]))
        out.append(mline("Tier 1+2", m["t2"]))
        out.append(mline("Tier 1+2+3", m["t3"]))
    # Round-wide grand multi: every leg of the tier across all games into one price.
    out.append("\n" + "=" * 60)
    out.append("ROUND-WIDE GRAND MULTI (all games combined):")
    def gline(label, legs):
        odds, n, miss = _multi(legs)
        extra = f", {miss} unpriced" if miss else ""
        return f"    {label}: ${odds:,.2f}  ({n} legs{extra})"
    out.append(gline("Tier 1", all_t1))
    out.append(gline("Tier 1+2", all_t2))
    out.append(gline("Tier 1+2+3", all_t3))
    out.append("\nNote: combined prices are the fair product of legs. Same-game multi "
               "legs are correlated, so Sportsbet's actual multi price will differ; big "
               "round-wide multis also exceed Sportsbet's per-multi leg limit.")
    return "\n".join(out)


def render_html(games, gen) -> str:
    C = {"green": "#1a9e6a", "amber": "#c0890f", "ink": "#0c2f6b", "mut": "#5b6f96"}
    rows = []
    def legs_html(legs, color):
        return "".join(
            f'<li><b>{b["player"]}</b> <span style="color:{C["mut"]}">({b["team"][:3].strip()})</span> '
            f'&mdash; {b["n"]}+ {b["unit"]} @ <b>${b["price"]:.2f}</b> '
            f'<span style="color:{color}">model {round(b["mp"]*100)}% · +{round(b["edge"]*100)}%</span></li>'
            for b in legs)
    def goals_html(legs):
        def line(b):
            return f'{b["n"]}+ goals' if b["proj"] >= GOAL_NUM_MIN else "anytime goal (1+)"
        def odds(b):
            return f' @ <b>${b["price"]:.2f}</b>' if b.get("price") else ""
        return "".join(
            f'<li><b>{b["player"]}</b> <span style="color:{C["mut"]}">({b["team"][:3].strip()})</span> '
            f'&mdash; <b>{line(b)}</b>{odds(b)} <span style="color:{C["mut"]}">{round(b["p1"]*100)}% anytime · '
            f'proj {b["proj"]:.1f}</span></li>'
            for b in legs)
    def multi_html(p):
        m = multis(p)
        def cell(label, t):
            odds, n, miss = t
            extra = f' <span style="color:{C["mut"]};font-weight:400">+{miss} unpriced</span>' if miss else ""
            return (f'<td style="padding:4px 14px 4px 0"><div style="color:{C["mut"]};font-size:11px">{label}</div>'
                    f'<div style="font-size:16px;font-weight:700">${odds:,.2f}</div>'
                    f'<div style="color:{C["mut"]};font-size:11px">{n} legs{extra}</div></td>')
        return ('<div style="margin:6px 0 4px;font-weight:700;color:#0c2f6b">Combined multi '
                '<span style="font-weight:400;color:#5b6f96;font-size:12px">(fair = product of legs)</span></div>'
                f'<table style="border-collapse:collapse"><tr>{cell("Tier 1", m["t1"])}'
                f'{cell("Tier 1+2", m["t2"])}{cell("Tier 1+2+3", m["t3"])}</tr></table>')
    all_t1, all_t2, all_t3 = [], [], []
    for g in games:
        if not any("od_ladder" in r for r in g["home_view"] + g["away_view"]):
            continue
        p = game_picks(g)
        if not (p["t1"] or p["t2_add"] or p["goals"]):
            continue
        all_t1 += list(p["t1"])
        all_t2 += list(p["t1"]) + list(p["t2_add"])
        all_t3 += list(p["t1"]) + list(p["t2_add"]) + list(p["goals"])
        rows.append(
            f'<h3 style="margin:22px 0 6px;color:{C["ink"]}">{g["home"]} v {g["away"]}</h3>'
            f'<div style="color:{C["mut"]};font-size:13px;margin-bottom:8px">R{g["round"]} · {fmt_awst(g)} · {g.get("venue","")}</div>'
            f'<div style="font-weight:700;color:{C["green"]}">Tier 1 — highest confidence (greens)</div>'
            f'<ul style="margin:4px 0 10px">{legs_html(p["t1"], C["green"]) or "<li><i>none</i></li>"}</ul>'
            f'<div style="font-weight:700;color:{C["amber"]}">Tier 2 — mid (tier 1 + ambers)</div>'
            f'<ul style="margin:4px 0 10px">{legs_html(p["t2_add"], C["amber"]) or "<li><i>no new amber picks</i></li>"}</ul>'
            f'<div style="font-weight:700;color:{C["mut"]}">Tier 3 — lowest (tier 2 + goal scorers)</div>'
            f'<ul style="margin:4px 0 10px">{goals_html(p["goals"]) or "<li><i>no credible goal scorers</i></li>"}</ul>'
            f'{multi_html(p)}')
    def grand_cell(label, legs):
        odds, n, miss = _multi(legs)
        extra = f' <span style="font-weight:400">+{miss} unpriced</span>' if miss else ""
        return (f'<td style="padding:6px 18px 6px 0"><div style="color:{C["mut"]};font-size:11px">{label}</div>'
                f'<div style="font-size:18px;font-weight:700;color:{C["ink"]}">${odds:,.2f}</div>'
                f'<div style="color:{C["mut"]};font-size:11px">{n} legs{extra}</div></td>')
    grand = ('<h3 style="margin:26px 0 4px;color:#0c2f6b">Round-wide grand multi '
             '<span style="font-weight:400;color:#5b6f96;font-size:12px">(all games combined)</span></h3>'
             f'<table style="border-collapse:collapse"><tr>{grand_cell("Tier 1", all_t1)}'
             f'{grand_cell("Tier 1+2", all_t2)}{grand_cell("Tier 1+2+3", all_t3)}</tr></table>')
    return (f'<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:640px;'
            f'margin:0 auto;color:{C["ink"]}">'
            f'<h2 style="margin:0 0 2px">PuntersMate — round bet summary</h2>'
            f'<div style="color:{C["mut"]};font-size:12px;margin-bottom:6px">page generated {gen} · '
            f'tiers are cumulative · model edges ignore the bookie margin</div>'
            f'{"".join(rows)}{grand}'
            f'<div style="color:{C["mut"]};font-size:11px;margin-top:18px">Combined multi prices are the '
            f'fair product of the leg odds. Same-game multi legs are correlated, so Sportsbet\'s actual '
            f'multi price will differ. Not betting advice.</div></div>')


# ── slate rendering ────────────────────────────────────────────────────────────

_RG = ("Model output only — not betting advice. Prices were live at build; markets "
       "move. Set a limit before you start. Gamble responsibly: 1800 858 858 · "
       "gamblinghelponline.org.au")

# Expectation-setting disclaimer that leads every digest: this is the convenient
# read of the model, not a get-rich scheme. Counters the historical over-promise
# and keeps the framing anti-hype (research tool, not a tipping service).
_DISCLAIMER = (
    "What this is (and what it isn't): the simple version. I crunch the week's "
    "disposal and fantasy numbers against the live odds so you don't have to wade "
    "through the raw data yourself. It is NOT a money-printer — the model just finds "
    "spots where the bookies look a bit soft, the edges are small, plenty of these "
    "legs will lose, and no week is a sure thing. Only ever bet what you're happy to "
    "lose.")

_DISCLAIMER_HTML = (
    '<div style="font-size:12px;color:#5b6f96;background:#f4f6fb;border:1px solid '
    '#e2e8f4;border-radius:6px;padding:10px 12px;margin:6px 0 16px">'
    '<b style="color:#0c2f6b">What this is (and what it isn\'t).</b> The simple version '
    '&mdash; I crunch the week\'s disposal &amp; fantasy numbers against the live odds so '
    'you don\'t have to wade through the raw data yourself. It\'s <b>not</b> a money-printer: '
    'the model just finds spots where the bookies look a bit soft &mdash; the edges are '
    'small, plenty of these legs will lose, and no week is a sure thing. Only ever bet what '
    'you\'re happy to lose.</div>')


def render_slate_text(games, gen, include_monday=False) -> str:
    up = _upcoming(games, include_monday)
    out = [f"PuntersMate — round slate (page generated {gen})", "=" * 60]
    out.append("\n" + _DISCLAIMER)
    out.append("\nTHE GAME PLAYS  —  one same-game multi per match")
    for g in up:
        gp = game_play(g)
        if not gp:
            continue
        odds, n, miss = gp["fair"]
        out.append(f"\n  {g['home']} v {g['away']}  ·  {fmt_awst(g)}")
        out += [f"    - {_leg_txt(b)}" for b in gp["legs"]]
        out.append(f"    Fair ${odds:.2f} ({n} legs)  —  {gp['note']}")
        out.append("    Slip: $______")
    dms = day_multis(up)
    if dms:
        out.append("\n\nTHE DAY MULTIS  —  best leg per game, across the day "
                   "(cross-game; slip ~ fair)")
        for dm in dms:
            odds, n, miss = dm["fair"]
            out.append(f"\n  {dm['day']}:  fair ${odds:.2f} ({n} legs)")
            out += [f"    - {_leg_txt(b)}" for b in dm["legs"]]
    sw = weekend_swing(up)
    odds, n, miss = sw["fair"]
    out.append(f"\n\nTHE WEEKEND SWING  —  {n} legs, cross-game  ·  fair ${odds:.2f}")
    out += [f"    - {_leg_txt(b)}" for b in sw["legs"]]
    if sw["pairs"]:
        out.append("    Note: same-game pairs correlate (slip slightly shorter): "
                   + "; ".join(sw["pairs"]))
    out.append("\n" + "-" * 60)
    out.append(_RG)
    return "\n".join(out)


def render_slate_html(games, gen, include_monday=False) -> str:
    C = {"green": "#1a9e6a", "ink": "#0c2f6b", "mut": "#5b6f96"}
    up = _upcoming(games, include_monday)

    def leg_li(b):
        return (f'<li><b>{b["player"]}</b> <span style="color:{C["mut"]}">'
                f'({b["team"][:3].strip()})</span> &mdash; {b["n"]}+ {b["unit"]} @ '
                f'<b>${b["price"]:.2f}</b> <span style="color:{C["mut"]};font-size:12px">'
                f'model {round(b["mp"]*100)}% · +{round(b["edge"]*100)}%</span></li>')

    blocks = []
    gp_html = []
    for g in up:
        gp = game_play(g)
        if not gp:
            continue
        odds, n, miss = gp["fair"]
        gp_html.append(
            f'<div style="margin:14px 0 2px;font-weight:700;color:{C["ink"]}">{g["home"]} v {g["away"]}</div>'
            f'<div style="color:{C["mut"]};font-size:12px">{fmt_awst(g)}</div>'
            f'<ul style="margin:4px 0 4px">{"".join(leg_li(b) for b in gp["legs"])}</ul>'
            f'<div style="font-size:13px"><b>Fair ${odds:.2f}</b> '
            f'<span style="color:{C["mut"]}">({n} legs) &mdash; {gp["note"]}</span></div>')
    blocks.append(
        f'<h3 style="margin:20px 0 2px;color:{C["ink"]}">The Game Plays</h3>'
        f'<div style="color:{C["mut"]};font-size:12px;margin-bottom:2px">One same-game '
        f'multi per match &mdash; a result to chase all weekend.</div>' + "".join(gp_html))

    dms = day_multis(up)
    if dms:
        dm_html = []
        for dm in dms:
            odds, n, miss = dm["fair"]
            dm_html.append(
                f'<div style="margin:10px 0 2px;font-weight:700;color:{C["ink"]}">{dm["day"]} '
                f'&mdash; <span style="color:{C["green"]}">${odds:.2f}</span></div>'
                f'<ul style="margin:2px 0 4px">{"".join(leg_li(b) for b in dm["legs"])}</ul>')
        blocks.append(
            f'<h3 style="margin:22px 0 2px;color:{C["ink"]}">The Day Multis</h3>'
            f'<div style="color:{C["mut"]};font-size:12px;margin-bottom:2px">Best leg per '
            f'game, across the day. Cross-game &mdash; your slip should match.</div>'
            + "".join(dm_html))

    sw = weekend_swing(up)
    odds, n, miss = sw["fair"]
    pair_note = (f'<div style="color:{C["mut"]};font-size:12px;margin-top:4px">Same-game '
                 f'pairs pull together (slip slightly shorter): {"; ".join(sw["pairs"])}.</div>'
                 if sw["pairs"] else "")
    blocks.append(
        f'<h3 style="margin:22px 0 2px;color:{C["ink"]}">The Weekend Swing</h3>'
        f'<div style="color:{C["mut"]};font-size:12px">The big one &mdash; {n} legs across '
        f'the round, fair <b>${odds:.2f}</b>.</div>'
        f'<ul style="margin:4px 0 4px">{"".join(leg_li(b) for b in sw["legs"])}</ul>{pair_note}')

    return (f'<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
            f'max-width:640px;margin:0 auto;color:{C["ink"]}">'
            f'<h2 style="margin:0 0 2px">PuntersMate — round slate</h2>'
            f'<div style="color:{C["mut"]};font-size:12px;margin-bottom:6px">page generated '
            f'{gen} · pick the slate that matches your appetite · model edges ignore '
            f'the bookie margin</div>{_DISCLAIMER_HTML}{"".join(blocks)}'
            f'<div style="color:{C["mut"]};font-size:11px;margin-top:18px">{_RG}</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="docs/index.html")
    ap.add_argument("--out", default="round_email.html")
    ap.add_argument("--format", choices=["slate", "tiers"], default="slate",
                    help="slate = Game Plays / Day Multis / Weekend Swing (default); "
                         "tiers = legacy cumulative three-tier view")
    ap.add_argument("--include-monday", action="store_true",
                    help="keep Monday (AWST) games (excluded by default)")
    ap.add_argument("--html-only", action="store_true")
    args = ap.parse_args()
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    games, gen = load_games(args.page)
    if args.format == "tiers":
        Path(args.out).write_text(render_html(games, gen), encoding="utf-8")
        text = render_text(games, gen)
    else:
        Path(args.out).write_text(
            render_slate_html(games, gen, args.include_monday), encoding="utf-8")
        text = render_slate_text(games, gen, args.include_monday)
    if not args.html_only:
        print(text)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
