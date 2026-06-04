"""
Build a tiered round-bet email summary from the built page (docs/index.html).

Reads the embedded DATA so the picks match exactly what's shown on the site, then
distils each imminent game into three cumulative confidence tiers:

  1. Highest  - every GREEN (edge >= 5%) disposal/fantasy pick. One bet per player:
                if a player is green in both markets, keep the higher-odds leg.
  2. Mid      - tier 1 plus AMBER (0-5% edge) picks (players green in neither market
                but amber in at least one), again the higher-odds leg per player.
  3. Lowest   - tier 2 plus 1-3 goal scorers per game whose goal projection > 2.0,
                each shown with the number of goals to back (floor of the projection).

Green/amber is computed with the same floor + EV maths the page uses:
  disposal floor = floor(proj - z*sigma), priced at that exact rung;
  fantasy        = the best-edge ladder rung AT OR BELOW the floor (coarse 5-step
                   ladder), model ~ Normal(proj, sigma); edge = model_p*price - 1.

    python round_email.py                      # text summary + writes round_email.html
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
                    goals.append({"player": r["player"], "team": team, "proj": gp,
                                  "p1": p1, "n": math.floor(gp) if gp >= GOAL_NUM_MIN else 1})
    t2_add = [v for k, v in ambers.items() if k not in greens]
    goals = sorted(goals, key=lambda x: -x["p1"])[:GOALS_PER_GAME]   # highest anytime % first
    by_edge = lambda L: sorted(L, key=lambda x: -x["edge"])
    return {"t1": by_edge(greens.values()), "t2_add": by_edge(t2_add), "goals": goals}


# ── rendering ─────────────────────────────────────────────────────────────────

def _leg_txt(b):
    return (f"{b['player']} ({b['team'][:3].strip()}) — {b['n']}+ {b['unit']} @ ${b['price']:.2f}"
            f"  [model {round(b['mp']*100)}%, +{round(b['edge']*100)}%]")


def _goal_txt(b):
    line = f"{b['n']}+ goals" if b["proj"] >= GOAL_NUM_MIN else "anytime goal (1+)"
    return f"{b['player']} ({b['team'][:3].strip()}) — {line}  [{round(b['p1']*100)}% anytime, proj {b['proj']:.1f}]"


def render_text(games, gen) -> str:
    out = [f"PuntersMate — round bet summary (page generated {gen})", "=" * 60]
    for g in games:
        if not any("od_ladder" in r for r in g["home_view"] + g["away_view"]):
            continue
        p = game_picks(g)
        if not (p["t1"] or p["t2_add"] or p["goals"]):
            continue
        out.append(f"\n{g['home']} v {g['away']}  ·  R{g['round']} · {fmt_awst(g)} · {g.get('venue','')}")
        out.append("  TIER 1 — highest confidence (greens):")
        out += [f"    • {_leg_txt(b)}" for b in p["t1"]] or ["    (none)"]
        out.append("  TIER 2 — mid confidence (tier 1 + ambers):")
        out += [f"    • {_leg_txt(b)}" for b in p["t2_add"]] or ["    (no new amber picks)"]
        out.append("  TIER 3 — lowest confidence (tier 2 + goal scorers):")
        out += [f"    • {_goal_txt(b)}" for b in p["goals"]] or ["    (no 2.0+ goal projections)"]
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
        return "".join(
            f'<li><b>{b["player"]}</b> <span style="color:{C["mut"]}">({b["team"][:3].strip()})</span> '
            f'&mdash; <b>{line(b)}</b> <span style="color:{C["mut"]}">{round(b["p1"]*100)}% anytime · '
            f'proj {b["proj"]:.1f}</span></li>'
            for b in legs)
    for g in games:
        if not any("od_ladder" in r for r in g["home_view"] + g["away_view"]):
            continue
        p = game_picks(g)
        if not (p["t1"] or p["t2_add"] or p["goals"]):
            continue
        rows.append(
            f'<h3 style="margin:22px 0 6px;color:{C["ink"]}">{g["home"]} v {g["away"]}</h3>'
            f'<div style="color:{C["mut"]};font-size:13px;margin-bottom:8px">R{g["round"]} · {fmt_awst(g)} · {g.get("venue","")}</div>'
            f'<div style="font-weight:700;color:{C["green"]}">Tier 1 — highest confidence (greens)</div>'
            f'<ul style="margin:4px 0 10px">{legs_html(p["t1"], C["green"]) or "<li><i>none</i></li>"}</ul>'
            f'<div style="font-weight:700;color:{C["amber"]}">Tier 2 — mid (tier 1 + ambers)</div>'
            f'<ul style="margin:4px 0 10px">{legs_html(p["t2_add"], C["amber"]) or "<li><i>no new amber picks</i></li>"}</ul>'
            f'<div style="font-weight:700;color:{C["mut"]}">Tier 3 — lowest (tier 2 + goal scorers)</div>'
            f'<ul style="margin:4px 0 10px">{goals_html(p["goals"]) or "<li><i>no 2.0+ goal projections</i></li>"}</ul>')
    return (f'<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:640px;'
            f'margin:0 auto;color:{C["ink"]}">'
            f'<h2 style="margin:0 0 2px">PuntersMate — round bet summary</h2>'
            f'<div style="color:{C["mut"]};font-size:12px;margin-bottom:6px">page generated {gen} · '
            f'tiers are cumulative · model edges ignore the bookie margin</div>'
            f'{"".join(rows)}</div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="docs/index.html")
    ap.add_argument("--out", default="round_email.html")
    ap.add_argument("--html-only", action="store_true")
    args = ap.parse_args()
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    games, gen = load_games(args.page)
    Path(args.out).write_text(render_html(games, gen), encoding="utf-8")
    if not args.html_only:
        print(render_text(games, gen))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
