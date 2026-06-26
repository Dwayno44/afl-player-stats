"""
Score the live page's pre-game predictions for a round against actual results.

Reads the model's predictions straight out of the built page (docs/index.html
embedded DATA -> per player D_proj, D_sigma, od_ladder), reproduces EXACTLY the
in-browser floor and green/amber value tint, then joins to the actual disposals in
games_2022_2026.csv for that round. Reports floor hit-rate (target = conf, 85%),
projection MAE/bias, and betting ROI on the value-tinted picks -- per game and for
the round so far. Only players with an actual result (game played) are scored.
"""
import argparse, json, re
from statistics import NormalDist
import numpy as np
import pandas as pd

ND = NormalDist()
ZCONF = ND.inv_cdf(0.85)        # 1.0364 — matches the page's ZCONF at conf=85%
VAL_CLEAR = 0.05
FLOOR_MIN = 10


def disp_floor(proj, sigma):
    if sigma is None or (isinstance(sigma, float) and np.isnan(sigma)):
        return max(0, int(np.floor(proj * 0.85)))
    return max(0, int(np.floor(proj - ZCONF * sigma)))


def tint(proj, sigma, ladder, floor):
    """('clear'|'border'|'', price_at_floor, model_p, ev) — exactly the page rule."""
    if not ladder or sigma in (None, 0) or (isinstance(sigma, float) and np.isnan(sigma)):
        return "", None, None, None
    price = ladder.get(str(floor))
    if price is None:
        return "", None, None, None
    mp = ND.cdf((proj - floor) / sigma)          # model P(disposals >= floor)
    ev = mp * price - 1
    cls = "clear" if ev >= VAL_CLEAR else ("border" if ev >= 0 else "")
    return cls, price, mp, ev


def load_predictions(html_path, rnd):
    html = open(html_path, encoding="utf-8").read()
    data = json.loads(re.search(r"const DATA = (\{.*?\});", html, re.S).group(1))
    rows = []
    for g in data["games"]:
        if g["round"] != rnd:
            continue
        for side, opp in [("home", "away"), ("away", "home")]:
            team, oppname = g[side], g[opp]
            for r in g[f"{side}_view"]:
                proj, sigma = r.get("D_proj"), r.get("D_sigma")
                if proj is None:
                    continue
                fl = disp_floor(proj, sigma)
                cls, price, mp, ev = tint(proj, sigma, r.get("od_ladder"), fl)
                rows.append({
                    "game": f"{g['home']} v {g['away']}", "team": team, "opp": oppname,
                    "player": r["player"], "proj": proj, "sigma": sigma,
                    "floor": fl, "shown": fl >= FLOOR_MIN,
                    "tint": cls, "price": price, "model_p": mp, "ev": ev,
                })
    return pd.DataFrame(rows)


def grade(df_pred, csv, rnd, season=2026):
    act = pd.read_csv(csv)
    act = act[(act["season"] == season) & (act["round"].astype(str) == str(rnd))]
    act["disposals"] = pd.to_numeric(act["disposals"], errors="coerce")
    key = {(r.team, r.player): r.disposals for r in act.itertuples()}
    df = df_pred.copy()
    df["actual"] = [key.get((t, p)) for t, p in zip(df["team"], df["player"])]
    return df[df["actual"].notna()].copy()   # only played


def block(df, label):
    if not len(df):
        print(f"  {label:<26} (no players)"); return
    hit = (df["actual"] >= df["floor"]).mean()
    err = df["actual"] - df["proj"]
    line = (f"  {label:<26} n={len(df):3d}  floorHit {hit*100:5.1f}%  "
            f"projMAE {err.abs().mean():5.2f}  bias {err.mean():+5.2f}")
    print(line)


def bet_block(df, label):
    """ROI on value-tinted picks: stake 1u on (floor+) at the floor price."""
    v = df[df["tint"].isin(["clear", "border"]) & df["price"].notna()]
    if not len(v):
        print(f"  {label:<26} (no value picks)"); return
    win = v["actual"] >= v["floor"]
    pnl = np.where(win, v["price"] - 1, -1.0)
    print(f"  {label:<26} n={len(v):3d}  win {win.mean()*100:5.1f}%  "
          f"ROI {pnl.sum()/len(v)*100:+6.1f}%  profit {pnl.sum():+5.2f}u")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=13)
    ap.add_argument("--html", default="docs/index.html")
    ap.add_argument("--csv", default="games_2022_2026.csv")
    args = ap.parse_args()

    pred = load_predictions(args.html, args.round)
    graded = grade(pred, args.csv, args.round)
    games = list(dict.fromkeys(pred["game"]))
    played = set(graded["game"])

    print(f"\n{'='*72}\n  ROUND {args.round} — model vs actual (floor conf 85%, target floorHit ~85%)")
    print(f"  {len(played)}/{len(games)} games played so far\n{'='*72}")

    print("\n— PER GAME —")
    for gm in games:
        gp = graded[graded["game"] == gm]
        status = "" if gm in played else "  [not played / no results yet]"
        print(f"\n {gm}{status}")
        if not len(gp):
            continue
        block(gp, "all projected (played)")
        block(gp[gp["shown"]], "floor>=10 (shown)")
        block(gp[gp["tint"].isin(["clear", "border"])], "amber+green")
        bet_block(gp, "value-pick ROI")

    print(f"\n\n— ROUND {args.round} SO FAR (totals) —")
    block(graded, "all projected (played)")
    block(graded[graded["shown"]], "floor>=10 (shown)")
    block(graded[graded["tint"] == "clear"], "GREEN (clear value)")
    block(graded[graded["tint"] == "border"], "AMBER (borderline)")
    block(graded[graded["tint"].isin(["clear", "border"])], "amber+green combined")
    print()
    bet_block(graded, "value-pick ROI (all)")
    bet_block(graded[graded["tint"] == "clear"], "GREEN-only ROI")
    bet_block(graded[graded["tint"] == "border"], "AMBER-only ROI")


if __name__ == "__main__":
    main()
