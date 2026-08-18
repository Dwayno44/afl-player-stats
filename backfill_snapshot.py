"""
Backfill a MISSED round's prediction snapshot from the historical CSV — floors only.

When the weekly snapshot didn't run (the app was closed on the scheduled day), a
round's pre-game predictions were never captured, so `scorecard.py grade` has no
baseline and the round silently drops out of the track record (this happened to
R18 and R19). The FLOOR, though, is fully deterministic: proj - z*sigma from
prior-games form. This tool reconstructs exactly what `matchup.team_view` would
have produced pre-round — it is fed ONLY games before the round, so it is
leak-free — and writes a snapshot JSON that `scorecard.py grade` reads unchanged.

What it CANNOT reconstruct: the green/amber value tints and their ROI. Those needed
the live Sportsbet ladders, which are gone once the round passes. So tint/price and
the odds ladders are left empty, and the snapshot is flagged `reconstructed: true`.
The floor-calibration numbers are genuine; there simply are no value picks for a
backfilled round.

    python backfill_snapshot.py --round 18
    python scorecard.py grade   --round 18
"""
import argparse
import json
from datetime import datetime, timezone

import pandas as pd

import matchup as M
import scorecard as S
import lineups as L


def fixture_csv_names(year, rnd):
    """(home, away) CSV team names for each CONCLUDED game of the round, named
    identically to scorecard.api_actuals so the game strings line up for grading."""
    token = L.get_token(verify=True)
    cid = L.compseason_id(year, token, True)
    out = []
    for m in L._matches(cid, rnd, token, True):
        if m.get("status") != "CONCLUDED":
            continue
        home = L.AFL2CSV.get(m["home"]["team"]["name"], m["home"]["team"]["name"])
        away = L.AFL2CSV.get(m["away"]["team"]["name"], m["away"]["team"]["name"])
        out.append((home, away))
    return out


def build_rows(df_pre, home, away):
    """Reconstruct both sides of one game via the SAME projection path the page uses."""
    rows = []
    for team, opp in [(home, away), (away, home)]:
        view = M.team_view(df_pre, team, opp, n=None)   # None = every player, as the web app does
        for _, r in view.iterrows():
            proj = r["D_proj"]
            if pd.isna(proj):
                continue
            proj = float(proj)
            sigma = None if pd.isna(r["D_sigma"]) else float(r["D_sigma"])
            fl = S.disp_floor(proj, sigma)              # identical rule to a live snapshot
            rows.append({
                "game": f"{home} v {away}", "team": team, "opp": opp,
                "player": r["player"], "proj": proj, "sigma": sigma,
                "floor": fl, "shown": fl >= S.FLOOR_MIN,
                "tint": "", "price": None,              # value picks unrecoverable
                "f_proj": None if pd.isna(r["F_proj"]) else float(r["F_proj"]),
                "f_sigma": None if pd.isna(r["F_sigma"]) else float(r["F_sigma"]),
                "f_ladder": None, "d_ladder": None,
            })
    return rows


def run(rnd, year=2026, csv="games_2022_2026.csv"):
    """Reconstruct and write a floors-only snapshot for one round. Returns its path.
    Importable so the CI safety net (ci_grade.py) can backfill missed rounds."""
    df = M.load(csv)
    df_pre = df[(df.season < year) | ((df.season == year) & (df["round"] < rnd))]
    if df_pre.empty:
        raise SystemExit(f"no games before {year} R{rnd} in {csv}")

    fixtures = fixture_csv_names(year, rnd)
    if not fixtures:
        raise SystemExit(f"no CONCLUDED games for {year} R{rnd} in the AFL API")

    rows = []
    for home, away in fixtures:
        rows += build_rows(df_pre, home, away)

    out = {
        "built": f"RECONSTRUCTED floors-only backfill ({datetime.now(timezone.utc).date()})",
        "year": year, "round": rnd, "reconstructed": True, "rows": rows,
    }
    path = S.SNAP.format(year=year, rnd=rnd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    shown = sum(r["shown"] for r in rows)
    print(f"backfill -> {path}: {len(rows)} player predictions ({shown} shown >={S.FLOOR_MIN}), "
          f"{len(fixtures)} games, floors-only (no value tints).")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--csv", default="games_2022_2026.csv")
    a = ap.parse_args()
    run(a.round, a.year, a.csv)
    print(f"Now: scorecard.py grade --round {a.round}")


if __name__ == "__main__":
    main()
