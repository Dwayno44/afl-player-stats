"""
Position-TYPE disposals-against — the "FNFGainz" hypothesis: do position archetypes
(inside mid, outside mid, ...) fare predictably against particular opponents?

This is the one untested variant of the opponent-concession family. Prior tests:
  - team-level concession: can't beat H2H (exp_concession)         -> null
  - concession by LINE (back/mid/fwd): no persistence (exp_line_da) -> null
  - concession by box-score role: worse than team-level             -> null
The gap: those all lumped inside and outside mids together. CBA (centre-bounce
attendance, AFL API 2025-26) splits them properly — Neale/Newcombe attend ~98% of
bounces, Whitfield/Dale/J.Daicos ~0% — and there is one plausible PERSISTENT
mechanism the line test couldn't see: team pressure. A low-pressure team conceding
uncontested ball to outside runners is a structural trait, not last week's noise.

Taxonomy (prior games only, leakage-free): R (ruck: ruck_contests>=15 or hitouts>=8),
then line_of()-style scores for D/F, remaining midfield profile split by average
CBA%: IM >=40 (inside), OM <=15 (outside), HM in between (hybrid/rotation).

Four questions, walk-forward on games_2022_2026.csv + cba_games.csv:
  1. PERSISTENCE — does a team's concede-to-position-type carry round to round?
     (lag-1 autocorr; the line-level version was ±0.04 = noise)
  2. PRESSURE TRAIT — is uncontested-ball-conceded a persistent team trait?
     (this CAN be persistent even if per-type disposal concession isn't)
  3. PROJECTION — does opp recent concede-to-(player's type), or opp uncontested-
     conceded, explain the residual the blend leaves behind? (per type)
  4. SELECTION — bucket picks by opponent softness to the player's type; do the
     soft-matchup buckets clear their floor / beat projection more often?
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from statistics import NormalDist
import matchup as M

ND = NormalDist()
Z = ND.inv_cdf(0.85)
FW = M.FORM_WINDOWS
IM_CBA, OM_CBA = 40.0, 15.0     # inside/outside mid split on avg CBA%
POS_NAMES = {"R": "ruck", "IM": "inside mid", "OM": "outside mid",
             "HM": "hybrid mid", "D": "defender", "F": "forward"}


def classify(prior):
    """R/IM/OM/HM/D/F from prior-games averages. Needs >=3 prior games with CBA
    data (so classification starts mid-2025). None = not classifiable yet."""
    cb = [r["cba_pct"] for r in prior if pd.notna(r.get("cba_pct"))]
    if len(cb) < 3:
        return None

    def a(k):
        v = [r.get(k) for r in prior if pd.notna(r.get(k))]
        return float(np.mean(v)) if v else 0.0

    if a("ruck_contests") >= 15 or a("hit_outs") >= 8:
        return "R"
    deff = a("rebound_50s") * 2 + a("one_percenters") + a("marks") - a("goals") * 2 - a("marks_inside_50") * 2
    mid = a("clearances") * 2 + a("contested_possessions") * 0.3 + a("tackles") * 0.3 - a("rebound_50s") - a("marks_inside_50")
    fwd = a("goals") * 3 + a("marks_inside_50") * 2 + a("behinds") - a("rebound_50s") * 2 - a("clearances")
    line = max(("D", deff), ("M", mid), ("F", fwd), key=lambda x: x[1])[0]
    cba = float(np.mean(cb))
    if line != "M":
        # high-CBA "forwards/defenders" are really mids rolling through — reassign
        if cba >= IM_CBA:
            return "IM"
        return line
    return "IM" if cba >= IM_CBA else ("OM" if cba <= OM_CBA else "HM")


def _h2h(prior, opp, season):
    g = [r for r in prior if r["opponent"] == opp]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (season - 3)) for r in g], float)
    return float((np.array([r["disposals"] for r in g], float) * w).sum() / w.sum())


def _autocorr(team_hist, keys, label):
    for k in keys:
        prev, cur = [], []
        for t in team_hist:
            seq = team_hist[t].get(k, [])
            for i in range(1, len(seq)):
                prev.append(seq[i - 1][2]); cur.append(seq[i][2])
        if len(prev) > 30:
            ac = np.corrcoef(prev, cur)[0, 1]
            print(f"    {label(k):<28} lag-1 autocorr {ac:+.3f}  ({len(prev)} pairs)"
                  + ("   <- persistent trait" if ac > 0.15 else "   ~ noise"))


def main():
    df = M.load("games_2022_2026.csv")
    df = df[df["disposals"].notna()].sort_values(["season", "round"]).reset_index(drop=True)

    # join CBA (AFL API rounds = csv round - 1; verified 98.9% disposal agreement)
    cba = pd.read_csv("cba_games.csv")
    cba["round"] = cba["round"] + 1
    df = df.merge(cba[["season", "round", "player", "cba_pct", "ruck_contests"]],
                  on=["season", "round", "player"], how="left")

    # assign each player-row a position from prior-games profile (leakage-free)
    phist0 = defaultdict(list)
    pos = []
    for rec in df.to_dict("records"):
        prior = phist0[(rec["player"], rec["team"])]
        pos.append(classify(prior))
        phist0[(rec["player"], rec["team"])].append(rec)
    df["pos"] = pos

    lab = df[df.pos.notna()]
    print(f"\n{'='*70}\n  0) TAXONOMY — {len(lab)} classified player-games (2025-26, CBA-based)\n{'='*70}")
    for p, sub in lab.groupby("pos"):
        names = (sub.groupby("player")["disposals"].mean().nlargest(3).index.tolist())
        print(f"    {POS_NAMES[p]:<12} n={len(sub):>5}  avg disp {sub['disposals'].mean():4.1f}"
              f"   e.g. {'; '.join(n.split(',')[0] for n in names)}")

    # per-game concession pools -------------------------------------------------
    # da_pos[(s,r,defending_team)][pos] = disposals conceded to that type
    # up_con[(s,r,defending_team)]     = uncontested possessions conceded (all seasons)
    da_pos = defaultdict(dict)
    up_con = {}
    for (s, r, team), grp in df.groupby(["season", "round", "team"]):
        opp = grp["opponent"].iloc[0]
        up = grp["uncontested_possessions"].sum()
        if pd.notna(up):
            up_con[(s, r, opp)] = float(up)
        for p, sub in grp.groupby("pos"):
            if p:
                da_pos[(s, r, opp)][p] = float(sub["disposals"].sum())

    hist_pos = defaultdict(lambda: defaultdict(list))    # team -> pos -> [(s,r,v)]
    hist_up = defaultdict(list)                          # team -> [(s,r,v)]
    for (s, r, t), d in da_pos.items():
        for p, v in d.items():
            hist_pos[t][p].append((s, r, v))
    for (s, r, t), v in up_con.items():
        hist_up[t].append((s, r, v))
    for t in hist_pos:
        for p in hist_pos[t]:
            hist_pos[t][p].sort()
    for t in hist_up:
        hist_up[t].sort()

    print(f"\n{'='*70}\n  1) PERSISTENCE — does concede-to-position-type carry round to round?\n{'='*70}")
    _autocorr(hist_pos, ["IM", "OM", "HM", "D", "F"], lambda k: f"disposals to {POS_NAMES[k]}")

    print(f"\n{'='*70}\n  2) PRESSURE TRAIT — is uncontested-ball-conceded persistent? (2022-26)\n{'='*70}")
    _autocorr({t: {"UP": v} for t, v in hist_up.items()}, ["UP"],
              lambda k: "uncontested poss conceded")
    # season-relative version (remove league drift between seasons)
    lg_up = {s: np.mean([v for (ss, rr, v) in sum(hist_up.values(), []) if ss == s])
             for s in df.season.unique()}
    rel = {t: {"UP": [(s, r, v / lg_up[s]) for (s, r, v) in seq]} for t, seq in hist_up.items()}
    _autocorr(rel, ["UP"], lambda k: "  ... season-relative")

    # 3 & 4) projection + selection, walk-forward round by round ----------------
    league_pos = defaultdict(list)   # pos -> concession values seen so far
    league_up = []                   # up-conceded values seen so far
    phist = defaultdict(list)
    rows = []
    for (s, r), rnd_df in df.groupby(["season", "round"], sort=True):
        for rec in rnd_df.to_dict("records"):
            opp, p = rec["opponent"], rec["pos"]
            key = (rec["player"], rec["team"]); prior = phist[key]
            sp = [x for x in prior if x["season"] == s]
            if p and len(sp) >= 3:
                d = [x["disposals"] for x in sp]
                windows = {f"L{w}": float(np.mean(d[-w:])) for w in FW}
                season_avg = float(np.mean(d))
                h2h = _h2h(prior, opp, s); has = pd.notna(h2h)
                base = M.project(windows, h2h, season_avg, has)
                sigma = float(np.std(d[-15:])) if len(d) >= 3 else season_avg * 0.2
                floor = max(0, np.floor(base - Z * sigma))
                seq = [v for (ds, dr, v) in hist_pos[opp].get(p, []) if (ds, dr) < (s, r)]
                sequ = [v for (ds, dr, v) in hist_up.get(opp, []) if (ds, dr) < (s, r)]
                soft = (float(np.mean(seq[-3:])) / float(np.mean(league_pos[p]))
                        if len(seq) >= 2 and len(league_pos[p]) >= 30 else np.nan)
                soft_up = (float(np.mean(sequ[-3:])) / float(np.mean(league_up))
                           if len(sequ) >= 2 and len(league_up) >= 30 else np.nan)
                rows.append({"actual": float(rec["disposals"]), "base": base,
                             "floor": floor, "soft": soft, "soft_up": soft_up, "pos": p})
        # pools update AFTER the whole round is scored (strictly-prior info only)
        for (ss, rr, t), dd in [(k, v) for k, v in da_pos.items() if (k[0], k[1]) == (s, r)]:
            for p, v in dd.items():
                league_pos[p].append(v)
        league_up.extend(v for (ss, rr, t), v in up_con.items() if (ss, rr) == (s, r))
        for rec in rnd_df.to_dict("records"):
            phist[(rec["player"], rec["team"])].append(rec)

    rec = pd.DataFrame(rows)
    print(f"\n{'='*70}\n  3) PROJECTION — does opponent softness explain the blend's residual?\n{'='*70}")
    resid = rec["actual"] - rec["base"]
    both = rec.dropna(subset=["soft"])
    print(f"    ALL types  n={len(both)}   corr(soft-to-type, residual) = "
          f"{np.corrcoef(both['soft'], both['actual']-both['base'])[0,1]:+.3f}")
    for p in ["IM", "OM", "HM", "D", "F"]:
        sub = rec[(rec.pos == p)].dropna(subset=["soft"])
        subu = rec[(rec.pos == p)].dropna(subset=["soft_up"])
        if len(sub) > 100:
            c1 = np.corrcoef(sub["soft"], sub["actual"] - sub["base"])[0, 1]
            c2 = np.corrcoef(subu["soft_up"], subu["actual"] - subu["base"])[0, 1]
            print(f"    {POS_NAMES[p]:<12} n={len(sub):>5}   soft-to-type {c1:+.3f}   "
                  f"opp-uncontested-conceded {c2:+.3f}")

    print(f"\n{'='*70}\n  4) SELECTION — do soft matchups clear the floor more often?\n{'='*70}")
    for name, sub in [("ALL classified", both),
                      ("inside mids", both[both.pos == "IM"]),
                      ("outside mids", both[both.pos == "OM"])]:
        if len(sub) < 300:
            continue
        sub = sub.copy()
        sub["q"] = pd.qcut(sub["soft"], 5, labels=["toughest", "q2", "q3", "q4", "softest"])
        sub["hit"] = (sub["actual"] >= sub["floor"]).astype(int)
        sub["beat"] = (sub["actual"] >= sub["base"]).astype(int)
        g = sub.groupby("q", observed=True).agg(n=("hit", "size"), floor_hit=("hit", "mean"),
                                                beat=("beat", "mean"))
        print(f"\n    {name} (n={len(sub)}) — bucketed by opp softness to player's type:")
        print(f"    {'bucket':<12}{'n':>7}{'floor_hit':>12}{'beat_proj':>12}")
        for q, row in g.iterrows():
            print(f"    {str(q):<12}{int(row['n']):>7}{row['floor_hit']*100:>11.1f}%{row['beat']*100:>11.1f}%")

    # outside mids vs opponent PRESSURE specifically (the one plausible mechanism)
    om = rec[(rec.pos == "OM")].dropna(subset=["soft_up"]).copy()
    if len(om) >= 300:
        om["q"] = pd.qcut(om["soft_up"], 5, labels=["high press", "q2", "q3", "q4", "low press"])
        om["hit"] = (om["actual"] >= om["floor"]).astype(int)
        om["beat"] = (om["actual"] >= om["base"]).astype(int)
        g = om.groupby("q", observed=True).agg(n=("hit", "size"), floor_hit=("hit", "mean"),
                                               beat=("beat", "mean"), resid=("actual", "mean"))
        g["resid"] = om.groupby("q", observed=True).apply(
            lambda x: (x["actual"] - x["base"]).mean(), include_groups=False)
        print(f"\n    OUTSIDE MIDS vs opponent pressure (uncontested conceded, n={len(om)}):")
        print(f"    {'bucket':<12}{'n':>7}{'floor_hit':>12}{'beat_proj':>12}{'resid':>9}")
        for q, row in g.iterrows():
            print(f"    {str(q):<12}{int(row['n']):>7}{row['floor_hit']*100:>11.1f}%"
                  f"{row['beat']*100:>11.1f}%{row['resid']:>+9.2f}")
        print("\n    (if low-press rows clear materially more, the TikTok thesis has legs;"
              "\n     flat = the market/blend already price it, same as every other DvP cut)")


if __name__ == "__main__":
    main()
