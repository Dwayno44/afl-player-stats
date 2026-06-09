"""
Position/line-level disposals-against — is concession concentrated by line, is it
persistent, and does it help SELECT floor players? (user hypothesis)

Team-total disposals-against was ~null (exp_team_da). The sharper question: a team
may concede ordinarily overall but consistently leak to one line (back / mid /
forward). If so, even without improving the projection it could tell you which
floor players to back — pick players whose line the upcoming opponent leaks to.

We test three things, all leakage-free on games_2022_2026.csv:
  1. PERSISTENCE — does a team's concede-to-line profile carry round to round?
     (lag-1 autocorrelation of relative concession by line). If ~0 it's noise and
     nothing downstream can work.
  2. PROJECTION signal — does opponent recent concede-to-(player's line) explain the
     residual the blend leaves behind? (correlation + OOS coefficient)
  3. SELECTION value — bucket picks by how soft the opponent has been to the
     player's line; do the soft-matchup buckets clear their floor / beat projection
     more often?

Line is assigned from the player's prior-games box-score profile (rebound50s/marks
-> back, clearances/contested -> mid, marks-i50/goals -> fwd, hitouts -> ruck).
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from statistics import NormalDist
import matchup as M

ND = NormalDist()
Z = ND.inv_cdf(0.85)
FW = M.FORM_WINDOWS


def line_of(prior):
    """'B'/'M'/'F'/'R' from a player's prior-games averages."""
    def a(k):
        v = [r.get(k) for r in prior if pd.notna(r.get(k))]
        return float(np.mean(v)) if v else 0.0
    if a("hit_outs") >= 8:
        return "R"
    deff = a("rebound_50s") * 2 + a("one_percenters") + a("marks") - a("goals") * 2 - a("marks_inside_50") * 2
    mid = a("clearances") * 2 + a("contested_possessions") * 0.3 + a("tackles") * 0.3 - a("rebound_50s") - a("marks_inside_50")
    fwd = a("goals") * 3 + a("marks_inside_50") * 2 + a("behinds") - a("rebound_50s") * 2 - a("clearances")
    return max(("B", deff), ("M", mid), ("F", fwd), key=lambda x: x[1])[0]


def _h2h(prior, opp, season):
    g = [r for r in prior if r["opponent"] == opp]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (season - 3)) for r in g], float)
    return float((np.array([r["disposals"] for r in g], float) * w).sum() / w.sum())


def main():
    df = M.load("games_2022_2026.csv")
    df = df[df["disposals"].notna()].sort_values(["season", "round"]).reset_index(drop=True)

    # assign each player-row a line from prior-games profile (leakage-free)
    phist0 = defaultdict(list)
    lines = []
    for rec in df.to_dict("records"):
        prior = phist0[(rec["player"], rec["team"])]
        lines.append(line_of(prior) if len(prior) >= 3 else None)
        phist0[(rec["player"], rec["team"])].append(rec)
    df["line"] = lines

    # team disposals conceded BY LINE per game: opponent's players of line L
    da_line = defaultdict(dict)            # (s,r,team_defending) -> {line: disposals}
    for (s, r, team), grp in df.groupby(["season", "round", "team"]):
        for L, sub in grp.groupby("line"):
            if L:
                # these players' OPPONENT conceded `sum` disposals to line L
                opp = sub["opponent"].iloc[0]
                da_line[(s, r, opp)][L] = float(sub["disposals"].sum())

    # chronological per-team concession-by-line history
    team_hist = defaultdict(lambda: defaultdict(list))   # team -> line -> [(s,r,val)]
    for (s, r, team), d in da_line.items():
        for L, v in d.items():
            team_hist[team][L].append((s, r, v))
    for t in team_hist:
        for L in team_hist[t]:
            team_hist[t][L].sort()

    # 1) PERSISTENCE: lag-1 autocorrelation of each team's concession by line,
    #    relative to that line's league mean per season.
    print(f"\n{'='*64}\n  1) PERSISTENCE — does concede-to-line carry round to round?\n{'='*64}")
    for L in ["B", "M", "F"]:
        prev, cur = [], []
        for t in team_hist:
            seq = team_hist[t][L]
            for i in range(1, len(seq)):
                prev.append(seq[i - 1][2]); cur.append(seq[i][2])
        if len(prev) > 30:
            ac = np.corrcoef(prev, cur)[0, 1]
            print(f"    line {L}: lag-1 autocorrelation {ac:+.3f}  ({len(prev)} pairs)"
                  + ("   <- some persistence" if ac > 0.15 else "   ~ noise"))

    # 2 & 3) projection + selection
    league = defaultdict(list)             # line -> running concession values
    phist = defaultdict(list)
    rows = []
    for rec in df.to_dict("records"):
        s, r, opp, L = rec["season"], rec["round"], rec["opponent"], rec["line"]
        key = (rec["player"], rec["team"]); prior = phist[key]
        sp = [x for x in prior if x["season"] == s]
        if L and len(sp) >= 3:
            d = [x["disposals"] for x in sp]
            windows = {f"L{w}": float(np.mean(d[-w:])) for w in FW}
            season_avg = float(np.mean(d))
            h2h = _h2h(prior, opp, s); has = pd.notna(h2h)
            base = M.project(windows, h2h, season_avg, has)
            sigma = float(np.std(d[-15:])) if len(d) >= 3 else season_avg * 0.2
            floor = max(0, np.floor(base - Z * sigma))
            # opponent recent concession to THIS player's line, vs league
            seq = [v for (ds, dr, v) in team_hist[opp][L] if (ds, dr) < (s, r)]
            lg = [v for v in league[L]]
            if len(seq) >= 2 and len(lg) >= 30:
                soft = float(np.mean(seq[-3:])) / float(np.mean(lg))
                rows.append({"actual": float(rec["disposals"]), "base": base,
                             "floor": floor, "soft": soft, "line": L})
        # update league + history pools AFTER use
        if (s, r, rec["team"]) in da_line:  # row contributes to its own line's pool once per team-game-line; approx
            pass
        if L:
            league[L].append(da_line.get((s, r, opp), {}).get(L, np.nan))
        phist[key].append(rec)

    rec = pd.DataFrame(rows).dropna(subset=["soft"])
    resid = rec["actual"] - rec["base"]
    print(f"\n{'='*64}\n  2) PROJECTION — does opp soft-to-line explain the residual?\n{'='*64}")
    print(f"    n={len(rec)}   corr(opp line-softness, residual) = "
          f"{np.corrcoef(rec['soft'], resid)[0,1]:+.3f}")

    print(f"\n{'='*64}\n  3) SELECTION — do soft-line matchups clear the floor more?\n{'='*64}")
    rec["q"] = pd.qcut(rec["soft"], 5, labels=["softest? no- toughest", "q2", "q3", "q4", "softest"])
    rec["hit"] = (rec["actual"] >= rec["floor"]).astype(int)
    rec["beat"] = (rec["actual"] >= rec["base"]).astype(int)
    g = rec.groupby("q", observed=True).agg(n=("hit", "size"), floor_hit=("hit", "mean"),
                                            beat_proj=("beat", "mean"), bias=("actual", "mean"))
    base_bias = (rec["actual"] - rec["base"]).mean()
    print(f"    bucket by opp softness-to-player's-line (toughest -> softest):")
    print(f"    {'bucket':<22}{'n':>6}{'floor_hit':>11}{'beat_proj':>11}")
    for q, row in g.iterrows():
        print(f"    {str(q):<22}{int(row['n']):>6}{row['floor_hit']*100:>10.1f}%{row['beat_proj']*100:>10.1f}%")
    print(f"\n    (if the softest bucket clears materially more than the toughest, it's a usable pick tilt)")


if __name__ == "__main__":
    main()
