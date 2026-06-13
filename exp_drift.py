"""
Line DRIFT — who does late money come for, and is the move informative?

We've used drift defensively (the Hardwick rule: suppress value picks whose price
moved against us). This asks the forward question: when the disposal ladder
shortens for a player (market raises its median), does he actually deliver more —
i.e. does the LATE line beat the EARLY line as a predictor?

Two modes:
  pilot : R13, from git history. The page was built with odds on Jun 5 (8a2108d)
          and again Jun 7 ~15:30 (35daee6) — two snapshots of the same ladders two
          days apart for the late-round games. Compute each player's vig-adjusted
          implied median at both times, the drift, and grade vs actuals.
  live  : R14, Wed build (3420d5f) vs a fresh Sportsbet pull NOW. Names the movers
          (late money for / against) and appends the capture to odds_log.jsonl so a
          real time-series accumulates for future rounds.

    python exp_drift.py pilot
    python exp_drift.py live
"""
import argparse, json, re, subprocess, time
from datetime import datetime, timezone
import numpy as np
import scorecard as SC
import sportsbet_odds as SB

PSTAR = 0.60          # vig-adjusted median crossing (fit out-of-sample in exp_market.py)
ODDS_LOG = "odds_log.jsonl"


def page_data(commit):
    out = subprocess.run(["git", "show", f"{commit}:docs/index.html"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"git show {commit} failed")
    return json.loads(re.search(r"const DATA = (\{.*?\});", out.stdout, re.S).group(1))


def ladders_at(commit, rnd):
    """{(team, csv_player): {'lad', 'proj', 'game'}} for priced players in a build."""
    out = {}
    for g in page_data(commit)["games"]:
        if g["round"] != rnd:
            continue
        for side in ("home_view", "away_view"):
            team = g[side.split("_")[0]]
            for r in g[side]:
                if r.get("od_ladder"):
                    out[(team, r["player"])] = {"lad": r["od_ladder"], "proj": r.get("D_proj"),
                                                "game": f"{g['home']} v {g['away']}"}
    return out


def med(lad, pstar=PSTAR):
    pts = sorted((int(n), 1.0 / p) for n, p in lad.items() if p and p > 1.0)
    if len(pts) < 2:
        return None
    xs = [n for n, _ in pts]; ps = [q for _, q in pts]
    if ps[0] < pstar:
        return float(xs[0])
    for i in range(1, len(pts)):
        if ps[i] < pstar:
            n0, p0, n1, p1 = xs[i - 1], ps[i - 1], xs[i], ps[i]
            return float(n0 + (p0 - pstar) * (n1 - n0) / (p0 - p1))
    return float(xs[-1])


def pilot():
    early = ladders_at("8a2108d", 13)            # Fri Jun 5 build
    late = ladders_at("35daee6", 13)             # Sun Jun 7 ~15:30 build
    actuals, _ = SC.api_actuals(2026, 13)
    rows = []
    for k, e in early.items():
        l = late.get(k)
        a = actuals.get(SC._key(*k))
        if not l or a is None:
            continue
        me, ml = med(e["lad"]), med(l["lad"])
        if me is None or ml is None:
            continue
        rows.append({"player": k[1], "game": l["game"], "proj": l["proj"],
                     "early": me, "late": ml, "drift": ml - me, "actual": a})
    import pandas as pd
    d = pd.DataFrame(rows)
    print(f"\nR13 drift pilot — {len(d)} players priced in BOTH builds (2 days apart)")
    a = d["actual"].to_numpy()
    mae = lambda p: float(np.mean(np.abs(p - a)))
    m_e, m_l = mae(d["early"].to_numpy()), mae(d["late"].to_numpy())
    verdict = "late beat early (move carried point-accuracy info)" if m_l < m_e - 1e-3 \
        else "late did NOT beat early on MAE (drift = bias info, not point accuracy, in this sample)"
    print(f"  MAE: our blend {mae(d['proj'].to_numpy()):.3f}   "
          f"EARLY median {m_e:.3f}   LATE median {m_l:.3f}   <- {verdict}")
    moved = d[d["drift"].abs() >= 0.5]
    print(f"  corr(drift, actual - early) = "
          f"{np.corrcoef(d['drift'], d['actual'] - d['early'])[0, 1]:+.3f}   "
          f"(movers only, n={len(moved)}: "
          f"{np.corrcoef(moved['drift'], moved['actual'] - moved['early'])[0, 1]:+.3f})")
    for name, m in [("late money FOR  (drift >= +0.5)", d["drift"] >= 0.5),
                    ("flat            (|drift| < 0.5)", d["drift"].abs() < 0.5),
                    ("late money AWAY (drift <= -0.5)", d["drift"] <= -0.5)]:
        s = d[m]
        if len(s):
            print(f"    {name}: n={len(s):3d}  actual-early {float((s['actual']-s['early']).mean()):+5.2f}  "
                  f"actual-late {float((s['actual']-s['late']).mean()):+5.2f}")
    big = d.reindex(d["drift"].abs().sort_values(ascending=False).index).head(8)
    print("  biggest moves:")
    for _, r in big.iterrows():
        print(f"    {r['player']:<22} {r['early']:5.1f} -> {r['late']:5.1f}  ({r['drift']:+.1f})   actual {r['actual']:.0f}")


def live(rnd=14, commit="3420d5f"):
    wed = ladders_at(commit, rnd)
    games = {}
    for (team, player), v in wed.items():
        games.setdefault(v["game"], set()).add((team, player))
    scraper = SB.make_scraper()
    events = SB.list_events(scraper)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, log = [], []
    for game, members in games.items():
        home, away = game.split(" v ")
        ev = SB.find_event(home, away, events=events, scraper=scraper)
        if not ev:
            print(f"  {game}: no live event (locked or started) — skipped")
            continue
        lad = SB.stat_ladder(ev["id"], "disposals", scraper)
        join = SB.match_players(list(lad), [p for _, p in members])
        seen_csv = set()
        for sb_name, csv_name in join.items():
            if csv_name in seen_csv:
                continue                      # two SB names joined one player — keep first
            key = next((k for k in members if k[1] == csv_name), None)
            if not key or key not in wed:
                continue
            me, ml = med(wed[key]["lad"]), med({str(k): v for k, v in lad[sb_name].items()})
            if me is None or ml is None or me > 45 or ml > 45:
                continue                      # >45 implied median = corrupt/mismatched ladder
            seen_csv.add(csv_name)
            rows.append({"game": game, "player": csv_name, "wed": me, "now": ml,
                         "drift": ml - me})
            log.append({"ts": ts, "round": rnd, "game": game, "player": csv_name,
                        "ladder": lad[sb_name]})
        time.sleep(0.3)
    with open(ODDS_LOG, "a", encoding="utf-8") as f:
        for item in log:
            f.write(json.dumps(item) + "\n")
    print(f"\nR{rnd} live drift — Wed build -> now   ({len(rows)} players; "
          f"{len(log)} ladders appended to {ODDS_LOG})")
    rows.sort(key=lambda r: -abs(r["drift"]))
    up = [r for r in rows if r["drift"] >= 0.5]
    dn = [r for r in rows if r["drift"] <= -0.5]
    print(f"\n  LATE MONEY FOR (market median up >= 0.5 disposals):")
    for r in up[:10]:
        print(f"    {r['player']:<22} {r['wed']:5.1f} -> {r['now']:5.1f}  ({r['drift']:+.1f})   {r['game']}")
    print(f"\n  LATE MONEY AWAY (median down >= 0.5):")
    for r in dn[:10]:
        print(f"    {r['player']:<22} {r['wed']:5.1f} -> {r['now']:5.1f}  ({r['drift']:+.1f})   {r['game']}")
    print(f"\n  flat: {len(rows) - len(up) - len(dn)} of {len(rows)}")


def log_now():
    """Capture-only: append current disposal ladders for every upcoming Sportsbet
    event to odds_log.jsonl (the time series the drift question needs). Run daily
    around rounds; safe to run any time — locked/absent events are skipped."""
    scraper = SB.make_scraper()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n_events = n_rows = 0
    with open(ODDS_LOG, "a", encoding="utf-8") as f:
        for ev in SB.list_events(scraper):
            try:
                lad = SB.stat_ladder(ev["id"], "disposals", scraper)
            except Exception:
                continue
            if not lad:
                continue
            n_events += 1
            game = f"{ev['home']} v {ev['away']}"
            for sb_name, ladder in lad.items():
                f.write(json.dumps({"ts": ts, "game": game, "sb_player": sb_name,
                                    "ladder": ladder}) + "\n")
                n_rows += 1
            time.sleep(0.3)
    print(f"odds-log: {n_rows} player ladders across {n_events} events -> {ODDS_LOG}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["pilot", "live", "log"])
    args = ap.parse_args()
    {"pilot": pilot, "live": live, "log": log_now}[args.mode]()


if __name__ == "__main__":
    main()
