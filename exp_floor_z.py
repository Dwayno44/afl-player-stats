"""
Floor-z recalibration — the shown slate (floor>=10) has held ~82-84% live and in the
backtest vs the 85% design (exp_floor_calib). The disposal left tail is heavier than
Normal for high-usage players (tags, early subs, role cuts), so the recent-15 std
under-states their downside and the floor sits ~2-3 pts optimistic exactly where it
matters — the mids people actually bet.

This finds the MINIMAL change that brings the shown slate to ~85% without wrecking the
all-players calibration (already ~85%) or gutting the floors' usefulness (a floor
dragged too low is information-free). Walk-forward, leakage-free on games_2022_2026.

Rules compared (all reuse the SAME walk-forward proj + sigma the model builds):
  base       floor = proj - z85*sigma                         (current)
  z=<v>      global confidence bump: proj - z(v)*sigma
  k=<v>      sigma multiplier: proj - z85*(k*sigma)           (~same family as z)
  cond a=<v> targeted: proj - (z85 + a*max(0,proj-15)/10)*sigma
             i.e. extra haircut only for high-projection players (leaves low untouched)

For each rule: shown-slate hit%, all-players hit%, shown count (picks kept), and the
average shown floor (how much information we give up). We want shown~85% at the
smallest cost to shown count + floor level.
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from statistics import NormalDist
import matchup as M

ND = NormalDist()
Z85 = ND.inv_cdf(0.85)
FW = M.FORM_WINDOWS


def _h2h(prior, opp, season):
    g = [r for r in prior if r["opponent"] == opp]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (season - 3)) for r in g], float)
    return float((np.array([r["disposals"] for r in g], float) * w).sum() / w.sum())


def collect(csv="games_2022_2026.csv"):
    df = M.load(csv)
    df = df[df["disposals"].notna()].sort_values(["season", "round"]).reset_index(drop=True)
    phist = defaultdict(list)
    rows = []
    for rec in df.to_dict("records"):
        s, opp = rec["season"], rec["opponent"]
        prior = phist[(rec["player"], rec["team"])]
        sp = [x for x in prior if x["season"] == s]
        if len(sp) >= 3:
            d = [x["disposals"] for x in sp]
            h2h = _h2h(prior, opp, s)
            proj = M.project({f"L{w}": float(np.mean(d[-w:])) for w in FW},
                             h2h, float(np.mean(d)), pd.notna(h2h))
            sigma = float(np.std(d[-15:]))
            rows.append({"season": s, "actual": float(rec["disposals"]),
                         "proj": proj, "sigma": sigma})
        phist[(rec["player"], rec["team"])].append(rec)
    return pd.DataFrame(rows)


def evaluate(r, label, floor):
    floor = np.maximum(0, np.floor(floor))
    hit = (r["actual"].values >= floor).astype(int)
    shown = floor >= 10
    sh_hit = hit[shown].mean() * 100 if shown.any() else float("nan")
    all_hit = hit.mean() * 100
    return {"rule": label, "all_hit": all_hit, "shown_hit": sh_hit,
            "shown_n": int(shown.sum()), "avg_shown_floor": float(floor[shown].mean())}


def main():
    r = collect()
    proj, sigma = r["proj"].values, r["sigma"].values
    print(f"\n  FLOOR-Z RECALIBRATION — walk-forward {len(r)} player-games (2022-26)")
    print(f"  target: bring SHOWN slate (floor>=10) to ~85% at least cost\n")
    hdr = f"  {'rule':<12}{'all hit':>9}{'shown hit':>11}{'shown n':>9}{'avg floor':>11}"
    print(hdr); print("  " + "-" * (len(hdr) - 2))

    results = []
    results.append(evaluate(r, "base (z85)", proj - Z85 * sigma))
    for conf in (0.87, 0.88, 0.89, 0.90):
        z = ND.inv_cdf(conf)
        results.append(evaluate(r, f"z={conf:.2f}", proj - z * sigma))
    for k in (1.15, 1.30):
        results.append(evaluate(r, f"k={k:.2f}", proj - Z85 * k * sigma))
    for a in (0.15, 0.25, 0.35, 0.50):
        zc = Z85 + a * np.maximum(0.0, proj - 15.0) / 10.0
        results.append(evaluate(r, f"cond a={a:.2f}", proj - zc * sigma))

    base_shown = results[0]["shown_n"]
    for x in results:
        flag = ""
        if 84.5 <= x["shown_hit"] <= 85.5:
            flag = "  <- on target"
        print(f"  {x['rule']:<12}{x['all_hit']:>8.1f}%{x['shown_hit']:>10.1f}%"
              f"{x['shown_n']:>9}{x['avg_shown_floor']:>11.1f}{flag}")
    print(f"\n  (base shown_n = {base_shown}; watch how many shown picks each rule keeps."
          "\n   'cond' adds the haircut only above proj 15, so it should hold the shown"
          "\n   slate to 85% while disturbing low-floor players and floor levels least.)")

    # per-season stability for the leading 'cond' candidate
    best = min((x for x in results if x["rule"].startswith("cond")),
               key=lambda x: abs(x["shown_hit"] - 85.0))
    a = float(best["rule"].split("=")[1])
    zc = Z85 + a * np.maximum(0.0, proj - 15.0) / 10.0
    floor = np.maximum(0, np.floor(proj - zc * sigma))
    shown = floor >= 10
    print(f"\n  per-season SHOWN hit under {best['rule']} (a={a}):")
    for s in sorted(r["season"].unique()):
        m = shown & (r["season"].values == s)
        if m.any():
            h = (r["actual"].values[m] >= floor[m]).mean() * 100
            print(f"    {int(s)}: {int(m.sum()):5d} games   {h:.1f}%")


if __name__ == "__main__":
    main()
