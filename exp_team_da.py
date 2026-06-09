"""
Does a team's RECENT disposals-against trend add signal? (user idea)

Distinct from exp_concession.py (which used a season-long concession rate): here we
ask whether the OPPONENT's disposals conceded over a short recent window — a defence
trending leaky/tight right now — improves a player's disposal projection beyond the
box-score blend already in the model.

Two signals, both leakage-free (opponent's games strictly before the target):
  level : opp recent DA (last 3 games) / running league-avg DA   (>1 = leaks more)
  trend : opp recent DA (last 3) / opp season-to-date DA          (>1 = getting worse)

We fit a coefficient on each out-of-sample (residual regression, 5-fold) so the
reported gain is honest, and report the correlation with the residual the baseline
leaves behind.
"""
from collections import defaultdict
import numpy as np
import pandas as pd
import matchup as M

FW = M.FORM_WINDOWS


def _h2h(prior, tgt, col):
    g = [r for r in prior if r["opponent"] == tgt["opponent"]]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (tgt["season"] - 3)) for r in g], float)
    return float((np.array([r[col] for r in g], float) * w).sum() / w.sum())


def build(df):
    df = df[df["disposals"].notna()].copy()
    df = df.sort_values(["season", "round"]).reset_index(drop=True)
    # team disposals FOR per (season, round, team); team's opponent that game
    team_for = df.groupby(["season", "round", "team"])["disposals"].sum().to_dict()
    opp_of = df.groupby(["season", "round", "team"])["opponent"].first().to_dict()
    # disposals AGAINST a team = the opponent's "for" total in that game
    da = {}
    for (s, r, t), opp in opp_of.items():
        v = team_for.get((s, r, opp))
        if v is not None:
            da[(s, r, t)] = v
    return df, da


def collect(df, da, min_prior=3):
    # chronological DA history per team
    team_da = defaultdict(list)   # team -> list[(season, round, DA)]
    for (s, r, t), v in sorted(da.items()):
        team_da[t].append((s, r, v))

    league = []                    # running league DA (for the level signal)
    phist = defaultdict(list)
    rows = []
    for rec in df.to_dict("records"):
        s, r, opp = rec["season"], rec["round"], rec["opponent"]
        key = (rec["player"], rec["team"]); prior = phist[key]
        sp = [x for x in prior if x["season"] == s]
        # opponent DA history strictly before this game
        odh = [v for (ds, dr, v) in team_da[opp] if (ds, dr) < (s, r)]
        odh_season = [v for (ds, dr, v) in team_da[opp] if ds == s and (ds, dr) < (s, r)]
        if len(sp) >= min_prior and len(odh) >= 3 and len(league) >= 50:
            W = {f"L{w}": float(np.mean([x["disposals"] for x in sp[-w:]])) for w in FW}
            has = bool([x for x in prior if x["opponent"] == opp])
            base = M.project(W, _h2h(prior, rec, "disposals"),
                             float(np.mean([x["disposals"] for x in sp])), has)
            recent = float(np.mean(odh[-3:]))
            lg = float(np.mean(league))
            level = recent / lg if lg else 1.0
            trend = (recent / float(np.mean(odh_season))) if len(odh_season) >= 3 else 1.0
            rows.append({"baseline": base, "actual": float(rec["disposals"]),
                         "level": level, "trend": trend})
        # update league running mean with this game's DA (now "prior")
        if (s, r, rec["team"]) in da:
            league.append(da[(s, r, rec["team"])])
        phist[key].append(rec)
    return pd.DataFrame(rows)


def cv_gain(d, feat, k=5, seed=0):
    d = d.dropna(subset=[feat]).reset_index(drop=True)
    base, act, x = d.baseline.to_numpy(), d.actual.to_numpy(), d[feat].to_numpy()
    resid = act - base
    idx = np.random.default_rng(seed).permutation(len(d))
    folds = np.array_split(idx, k); be, ae = [], []
    for j in range(k):
        te = folds[j]; tr = np.concatenate([folds[m] for m in range(k) if m != j])
        xt = x[tr] - x[tr].mean()
        b = float((xt @ resid[tr]) / (xt @ xt)) if (xt @ xt) > 0 else 0.0
        be.append(np.abs(base[te] - act[te]))
        ae.append(np.abs(base[te] + b * (x[te] - x[tr].mean()) - act[te]))
    return np.concatenate(be).mean(), np.concatenate(ae).mean()


def main():
    df = M.load("games_2022_2026.csv")
    df, da = build(df)
    rec = collect(df, da)
    a = rec.actual.to_numpy(); base = rec.baseline.to_numpy()
    mb = float(np.mean(np.abs(base - a)))
    r = a - base
    print(f"\n  DISPOSALS — opponent recent disposals-against signal")
    print(f"  {len(rec)} held-out games   baseline MAE {mb:.3f}\n  {'-'*52}")
    print(f"  corr(opp recent-DA LEVEL,  residual) = {np.corrcoef(rec.level, r)[0,1]:+.3f}")
    print(f"  corr(opp recent-DA TREND,  residual) = {np.corrcoef(rec.trend, r)[0,1]:+.3f}")
    for feat in ["level", "trend"]:
        b, ad = cv_gain(rec, feat)
        d = ad - b
        tag = "improves" if d < -1e-3 else ("~no gain" if abs(d) <= 1e-3 else "worse")
        print(f"  + {feat:<6}: {b:.3f} -> {ad:.3f}  ({d:+.3f}, {d/b*100:+.1f}%)  {tag}")


if __name__ == "__main__":
    main()
