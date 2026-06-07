"""
Standing per-round scorecard: grade the live page's pre-game disposal predictions
(floors + green/amber value tints) against ACTUAL results from the AFL API, per
game and for the round so far, and accumulate a one-row-per-round summary so the
value-bet ROI builds toward a real sample over weeks.

Why a snapshot: the page (docs/index.html) drops past games when it rebuilds, so
R13's predictions vanish once the round passes. We snapshot them to
`predictions_<year>_R<rd>.json` while they're live, then grade the snapshot later.

Why the API for actuals (not the CSV): the afltables CSV round numbering is offset
(its 'R13' = AFL R12). The AFL API shares the page's round numbering.

Usage:
    python scorecard.py snapshot --round 13      # capture predictions now (do this while live)
    python scorecard.py grade    --round 13      # grade vs API actuals, append to log
    python scorecard.py log                      # multi-round accumulated summary
"""
import argparse, json, os, re
from datetime import datetime, timezone
from statistics import NormalDist
import numpy as np
import pandas as pd
import requests
import lineups as L

ND = NormalDist()
ZCONF = ND.inv_cdf(0.85)          # page ZCONF at conf=85%
VAL_CLEAR, FLOOR_MIN = 0.05, 10
PSTATS = "https://api.afl.com.au/cfs/afl/playerStats/match/{}"
SNAP = "predictions_{year}_R{rnd}.json"
LOG = "scorecard_log.csv"


# ── prediction snapshot (from the live page) ─────────────────────────────────────
def disp_floor(proj, sigma):
    if sigma in (None, "") or (isinstance(sigma, float) and np.isnan(sigma)):
        return max(0, int(np.floor(proj * 0.85)))
    return max(0, int(np.floor(proj - ZCONF * sigma)))


def tint(proj, sigma, ladder, floor):
    """('clear'|'border'|'', price) — the page's value rule at the floor rung."""
    if not ladder or not sigma:
        return "", None
    price = ladder.get(str(floor))
    if price is None:
        return "", None
    ev = ND.cdf((proj - floor) / sigma) * price - 1
    return ("clear" if ev >= VAL_CLEAR else ("border" if ev >= 0 else "")), price


def snapshot(html, year, rnd):
    data = json.loads(re.search(r"const DATA = (\{.*?\});", open(html, encoding="utf-8").read(), re.S).group(1))
    rows = []
    for g in data["games"]:
        if g["round"] != rnd:
            continue
        for side, opp in [("home", "away"), ("away", "home")]:
            for r in g[f"{side}_view"]:
                proj, sigma = r.get("D_proj"), r.get("D_sigma")
                if proj is None:
                    continue
                fl = disp_floor(proj, sigma)
                cls, price = tint(proj, sigma, r.get("od_ladder"), fl)
                rows.append({"game": f"{g['home']} v {g['away']}", "team": g[side],
                             "opp": g[opp], "player": r["player"], "proj": proj,
                             "sigma": sigma, "floor": fl, "shown": fl >= FLOOR_MIN,
                             "tint": cls, "price": price})
    path = SNAP.format(year=year, rnd=rnd)
    json.dump({"built": data.get("generated"), "year": year, "round": rnd, "rows": rows},
              open(path, "w", encoding="utf-8"))
    print(f"snapshot -> {path}: {len(rows)} player predictions "
          f"({sum(r['shown'] for r in rows)} shown >={FLOOR_MIN}, "
          f"{sum(r['tint'] in ('clear','border') for r in rows)} value-tinted)")


# ── actuals (from the AFL API) ───────────────────────────────────────────────────
def api_actuals(year, rnd):
    token = L.get_token(verify=True)
    cid = L.compseason_id(year, token, True)
    h = {"User-Agent": L.UA, "x-media-mis-token": token}
    out, played = {}, set()
    for m in L._matches(cid, rnd, token, True):
        home = L.AFL2CSV.get(m["home"]["team"]["name"], m["home"]["team"]["name"])
        away = L.AFL2CSV.get(m["away"]["team"]["name"], m["away"]["team"]["name"])
        js = requests.get(PSTATS.format(m["providerId"]), headers=h, timeout=30, verify=True).json()
        if not js.get("homeTeamPlayerStats") or not js.get("awayTeamPlayerStats"):
            continue
        played.add(f"{home} v {away}")
        for sidekey, team in [("homeTeamPlayerStats", home), ("awayTeamPlayerStats", away)]:
            for p in js[sidekey]:
                nm = p["player"]["player"]["player"]["playerName"]
                d = (p["playerStats"].get("stats") or {}).get("disposals")
                if d is not None:
                    out[(team, L._norm(nm["surname"]), L._norm(L._strip_mid(nm["givenName"])))] = float(d)
    return out, played


def _key(team, player):
    sur, _, giv = player.partition(", ")
    return (team, L._norm(sur), L._norm(L._strip_mid(giv)))


# ── reporting ────────────────────────────────────────────────────────────────────
def _row(df):
    if not len(df):
        return None
    hit = float((df.actual >= df.floor).mean())
    err = df.actual - df.proj
    return dict(n=len(df), hit=hit, mae=float(err.abs().mean()), bias=float(err.mean()))


def _roi(df):
    v = df[df.tint.isin(["clear", "border"]) & df.price.notna()]
    if not len(v):
        return None
    win = (v.actual >= v.floor)
    pnl = np.where(win, v.price - 1, -1.0)
    return dict(n=len(v), win=float(win.mean()), roi=float(pnl.sum() / len(v)), profit=float(pnl.sum()))


def _fmt(label, r):
    if not r:
        print(f"  {label:<26} (none)"); return
    print(f"  {label:<26} n={r['n']:3d}  floorHit {r['hit']*100:5.1f}%  "
          f"MAE {r['mae']:5.2f}  bias {r['bias']:+5.2f}")


def grade(year, rnd, append=True):
    snap = json.load(open(SNAP.format(year=year, rnd=rnd), encoding="utf-8"))
    pred = pd.DataFrame(snap["rows"])
    actuals, played = api_actuals(year, rnd)
    pred["actual"] = [actuals.get(_key(t, p)) for t, p in zip(pred.team, pred.player)]
    pred["concluded"] = pred.game.isin(played)
    g = pred[pred.concluded & pred.actual.notna()].copy()
    page_games = list(dict.fromkeys(pred.game))
    conc = [x for x in page_games if x in played]

    print(f"\n{'='*72}\n  ROUND {rnd} SCORECARD — page predictions vs AFL API actuals")
    print(f"  {len(conc)}/{len(page_games)} games concluded   "
          f"(snapshot built {snap.get('built')})\n{'='*72}")
    for gm in conc:
        gp = g[g.game == gm]
        print(f"\n {gm}  (n={len(gp)})")
        _fmt("all projected", _row(gp))
        _fmt("floor>=10 (shown)", _row(gp[gp.shown]))
        _fmt("amber+green", _row(gp[gp.tint.isin(['clear', 'border'])]))
        r = _roi(gp)
        if r:
            print(f"  {'value-pick ROI':<26} n={r['n']:3d}  win {r['win']*100:5.1f}%  "
                  f"ROI {r['roi']*100:+6.1f}%  profit {r['profit']:+5.2f}u")

    print(f"\n— ROUND {rnd} SO FAR ({len(conc)} games) —")
    groups = {"overall": _row(g), "shown": _row(g[g.shown]),
              "green": _row(g[g.tint == 'clear']), "amber": _row(g[g.tint == 'border']),
              "value": _row(g[g.tint.isin(['clear', 'border'])])}
    _fmt("overall (all projected)", groups["overall"])
    _fmt("floor>=10 (shown)", groups["shown"])
    _fmt("GREEN (clear)", groups["green"])
    _fmt("AMBER (border)", groups["amber"])
    roi = _roi(g)
    if roi:
        print(f"\n  value-pick ROI: n={roi['n']}  win {roi['win']*100:.1f}%  "
              f"ROI {roi['roi']*100:+.1f}%  profit {roi['profit']:+.2f}u")
    if groups["shown"]:
        print(f"  calibration: shown-floor hit {groups['shown']['hit']*100:.1f}% vs 85% target")

    if append:
        complete = (len(conc) == len(page_games))
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "year": year, "round": rnd, "games_concluded": len(conc),
               "games_total": len(page_games), "complete": complete}
        for grp in ["overall", "shown", "value"]:
            r = groups[grp]
            if r:
                rec[f"{grp}_n"], rec[f"{grp}_hit"] = r["n"], round(r["hit"], 4)
                rec[f"{grp}_mae"], rec[f"{grp}_bias"] = round(r["mae"], 3), round(r["bias"], 3)
        if roi:
            rec.update(value_win=round(roi["win"], 4), value_roi=round(roi["roi"], 4),
                       value_profit=round(roi["profit"], 3))
        df = pd.DataFrame([rec])
        df.to_csv(LOG, mode="a", header=not os.path.exists(LOG), index=False)
        print(f"\n  logged to {LOG} (complete={complete})")


def show_log():
    if not os.path.exists(LOG):
        print("no scorecard_log.csv yet"); return
    df = pd.read_csv(LOG)
    comp = df[df.complete].drop_duplicates("round", keep="last")
    print("\n— ACCUMULATED (complete rounds) —")
    if len(comp):
        cols = ["round", "shown_n", "shown_hit", "shown_mae", "shown_bias",
                "value_n", "value_win", "value_roi", "value_profit"]
        print(comp[[c for c in cols if c in comp]].to_string(index=False))
        if "value_profit" in comp:
            print(f"\n  value bets: {int(comp.value_n.sum())} picks, "
                  f"cumulative profit {comp.value_profit.sum():+.2f}u, "
                  f"blended ROI {comp.value_profit.sum()/comp.value_n.sum()*100:+.1f}%")
            print(f"  floor calibration (shown): "
                  f"{(comp.shown_hit*comp.shown_n).sum()/comp.shown_n.sum()*100:.1f}% vs 85% target")
    else:
        print("no complete rounds logged yet (in-progress rounds aren't counted)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "grade"):
        s = sub.add_parser(name); s.add_argument("--round", type=int, required=True)
        s.add_argument("--year", type=int, default=2026)
        s.add_argument("--html", default="docs/index.html")
        s.add_argument("--no-log", action="store_true")
    sub.add_parser("log")
    a = ap.parse_args()
    if a.cmd == "snapshot":
        snapshot(a.html, a.year, a.round)
    elif a.cmd == "grade":
        grade(a.year, a.round, append=not a.no_log)
    elif a.cmd == "log":
        show_log()


if __name__ == "__main__":
    main()
