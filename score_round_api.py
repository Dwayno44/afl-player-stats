"""
Correct round scorer: grade the live page's R13 predictions against ACTUAL R13
results from the AFL API (same round numbering as the page's fixture).

NB: the afltables CSV round numbering is offset (its 'R13' = AFL R12), so the CSV
cannot be used to grade the page's R13 — we pull actuals from the API instead, and
only for CONCLUDED games ("round so far").
"""
import argparse, json, re
from statistics import NormalDist
import numpy as np
import pandas as pd
import requests
import lineups as L
import score_round as SR     # reuse disp_floor / tint / load_predictions

ND = NormalDist()
PSTATS = "https://api.afl.com.au/cfs/afl/playerStats/match/{}"


def api_actuals(year, rnd):
    """{(csv_team, 'Surname, Given'): disposals} for CONCLUDED games; plus the set
    of concluded 'home v away' game labels (CSV team names)."""
    token = L.get_token(verify=True)
    cid = L.compseason_id(year, token, True)
    h = {"User-Agent": L.UA, "x-media-mis-token": token}
    out, played = {}, set()
    for m in L._matches(cid, rnd, token, True):
        home = L.AFL2CSV.get(m["home"]["team"]["name"], m["home"]["team"]["name"])
        away = L.AFL2CSV.get(m["away"]["team"]["name"], m["away"]["team"]["name"])
        js = requests.get(PSTATS.format(m["providerId"]), headers=h, timeout=30, verify=True).json()
        if not js.get("homeTeamPlayerStats") or not js.get("awayTeamPlayerStats"):
            continue                                  # not played yet
        played.add(f"{home} v {away}")
        for side, team in [("homeTeamPlayerStats", home), ("awayTeamPlayerStats", away)]:
            for p in js[side]:
                nm = p["player"]["player"]["player"]["playerName"]
                d = (p["playerStats"].get("stats") or {}).get("disposals")
                if d is not None:
                    out[(team, f"{nm['surname']}, {nm['givenName']}")] = float(d)
    return out, played


def _norm_key(team, player):
    sur, _, giv = player.partition(", ")
    return (team, L._norm(sur), L._norm(L._strip_mid(giv)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=13)
    ap.add_argument("--html", default="docs/index.html")
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()

    pred = SR.load_predictions(args.html, args.round)
    actuals, played = api_actuals(args.year, args.round)
    # normalised-name lookup for robust joins (accents/middle initials)
    norm = {_norm_key(t, p): v for (t, p), v in actuals.items()}

    def lookup(team, player):
        if (team, player) in actuals:
            return actuals[(team, player)]
        return norm.get(_norm_key(team, player))

    pred["actual"] = [lookup(t, p) for t, p in zip(pred["team"], pred["player"])]
    pred["concluded"] = pred["game"].isin(played)
    graded = pred[pred["concluded"] & pred["actual"].notna()].copy()

    page_games = list(dict.fromkeys(pred["game"]))
    conc_page = [g for g in page_games if g in played]
    print(f"\n{'='*74}\n  ROUND {args.round} — page predictions vs ACTUAL (AFL API)  conf 85%")
    print(f"  page lists {len(page_games)} games; {len(conc_page)} concluded & scored")
    print(f"  unmatched page players in concluded games: "
          f"{(pred['concluded'] & pred['actual'].isna()).sum()} (late outs/subs/name)\n{'='*74}")

    print("\n— PER GAME (concluded) —")
    for gm in conc_page:
        gp = graded[graded["game"] == gm]
        print(f"\n {gm}   (n={len(gp)} played)")
        SR.block(gp, "all projected")
        SR.block(gp[gp["shown"]], "floor>=10 (shown)")
        SR.block(gp[gp["tint"].isin(["clear", "border"])], "amber+green")
        SR.bet_block(gp, "value-pick ROI")

    print(f"\n\n— ROUND {args.round} SO FAR (totals over {len(conc_page)} concluded games) —")
    SR.block(graded, "all projected")
    SR.block(graded[graded["shown"]], "floor>=10 (shown)")
    SR.block(graded[graded["tint"] == "clear"], "GREEN (clear value)")
    SR.block(graded[graded["tint"] == "border"], "AMBER (borderline)")
    SR.block(graded[graded["tint"].isin(["clear", "border"])], "amber+green combined")
    print()
    SR.bet_block(graded, "value-pick ROI (all)")
    SR.bet_block(graded[graded["tint"] == "clear"], "GREEN-only ROI")
    SR.bet_block(graded[graded["tint"] == "border"], "AMBER-only ROI")
    # floor-hit is a 1-sided 85% bet; show how calibration compares to target
    sh = graded[graded["shown"]]
    if len(sh):
        print(f"\n  calibration: shown-floor hit {((sh['actual']>=sh['floor']).mean()*100):.1f}% "
              f"vs 85% target ({len(sh)} picks)")


if __name__ == "__main__":
    main()
