"""
Market-as-input test: does the Sportsbet disposal ladder predict better than us?

We've only ever treated the market as the thing to BEAT. For pure prediction
accuracy it's the strongest public predictor available (a superset of our info).
Here we extract each player's MARKET-IMPLIED MEDIAN disposals from the N+ price
ladder in a historical page build (git: the round's odds build), and compare its
MAE against our blend projection on the same players' actuals — plus a simple
50/50 blend of ours and the market's.

Implied median: P(>=N) = 1/price (vig-inflated). We find where the implied curve
crosses p* and linearly interpolate. Because vig inflates every P, the raw 0.5
crossing sits high; we also report a vig-adjusted crossing (normalising by the
ladder's local overround is overkill for rung gaps; instead we test a small grid
of p* and report 0.5 plus the calibration-best, fit on HALF the players and
scored on the other half to stay honest).

    python exp_market.py --commit 8a2108d --round 13
"""
import argparse, json, re, subprocess
import numpy as np
import scorecard as SC


def page_at(commit):
    out = subprocess.run(["git", "show", f"{commit}:docs/index.html"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"git show failed: {out.stderr[:200]}")
    return json.loads(re.search(r"const DATA = (\{.*?\});", out.stdout, re.S).group(1))


def implied_median(ladder, pstar):
    """Interpolated N where implied P(>=N)=1/price crosses pstar."""
    pts = sorted((int(n), 1.0 / p) for n, p in ladder.items() if p and p > 1.0)
    if len(pts) < 2:
        return None
    xs = [n for n, _ in pts]; ps = [q for _, q in pts]
    if ps[0] < pstar:           # even the lowest rung is below pstar
        return float(xs[0])
    for i in range(1, len(pts)):
        if ps[i] < pstar:
            n0, p0, n1, p1 = xs[i-1], ps[i-1], xs[i], ps[i]
            return float(n0 + (p0 - pstar) * (n1 - n0) / (p0 - p1))
    return float(xs[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default="8a2108d")
    ap.add_argument("--round", type=int, default=13)
    args = ap.parse_args()

    data = page_at(args.commit)
    actuals, played = SC.api_actuals(2026, args.round)
    rows = []
    for g in data["games"]:
        if g["round"] != args.round:
            continue
        for side in ("home_view", "away_view"):
            team = g[side.split("_")[0]]
            for r in g[side]:
                lad = r.get("od_ladder")
                proj = r.get("D_proj")
                if not lad or proj is None:
                    continue
                a = actuals.get(SC._key(team, r["player"]))
                if a is None:
                    continue
                rows.append({"player": r["player"], "proj": proj, "actual": a,
                             "lad": lad})
    print(f"round {args.round} @ {args.commit}: {len(rows)} priced players with actuals")
    a = np.array([r["actual"] for r in rows])
    ours = np.array([r["proj"] for r in rows])
    mae = lambda p: float(np.mean(np.abs(np.asarray(p) - a)))

    # honest pstar selection: fit on even rows, score on odd rows
    fit_idx = np.arange(0, len(rows), 2); test_idx = np.arange(1, len(rows), 2)
    grid = [0.50, 0.52, 0.54, 0.56, 0.58, 0.60]
    best_p, best_err = 0.5, 1e9
    for ps in grid:
        m = [implied_median(rows[i]["lad"], ps) for i in fit_idx]
        ok = [j for j, v in enumerate(m) if v is not None]
        err = float(np.mean(np.abs(np.array([m[j] for j in ok]) -
                                   a[fit_idx][ok])))
        if err < best_err:
            best_err, best_p = err, ps

    for label, ps, idx in [("market median (raw p*=0.50)", 0.50, np.arange(len(rows))),
                           (f"market median (fit p*={best_p:.2f}, scored OOS)", best_p, test_idx)]:
        m = [implied_median(rows[i]["lad"], ps) for i in idx]
        ok = [j for j, v in enumerate(m) if v is not None]
        mm = np.array([m[j] for j in ok]); aa = a[idx][ok]; oo = ours[idx][ok]
        print(f"\n  {label}   (n={len(ok)})")
        print(f"    our blend        MAE {float(np.mean(np.abs(oo-aa))):.3f}")
        print(f"    market implied   MAE {float(np.mean(np.abs(mm-aa))):.3f}")
        print(f"    50/50 blend      MAE {float(np.mean(np.abs((mm+oo)/2-aa))):.3f}")


if __name__ == "__main__":
    main()
