"""
THE COMBINED-MODEL TEST — do many individually-weak levers add up?

This is the direct answer to the founding brainstorm (see BRAINSTORM.md): its §17
argued some signals "may not matter much alone but become powerful in combination,"
and §18 recommended exactly this — an **ensemble of a stable baseline plus a
LightGBM/XGBoost model** to capture interactions a one-lever-at-a-time test can't
see. Every other experiment tested levers individually and found them
noise/secondary. Here we throw them ALL into one gradient-boosted model and ask:
does the combination beat the simple season-anchored blend OUT OF SAMPLE?

Honest design:
  - Data: the AFL-API frame (cba_games.csv, ~14.6k player-games, 2025-26) — the only
    set with TOG + CBA + role stats. Enriched with environment levers (home/away,
    day/night, venue, round) from match metadata.
  - Features (all leakage-free, from games strictly before each target): form
    windows, season avg, H2H, volatility; TOG & per-minute rate; CBA level & trend;
    role (centre clearances, ruck contests, kick-ins); opponent disposals-against
    (recent & season); environment (home, night, venue, round); and the blend's own
    projection as a feature (so the tree starts from the strong baseline — the §18
    "baseline + ML adjustment" ensemble).
  - Split: TIME-BASED — train on 2025, test on 2026 (no random k-fold; a model that
    only wins by leaking the future is worthless). Early stopping on a 2025 tail.
  - Verdict: LightGBM test MAE vs the blend's test MAE on the SAME 2026 games. If the
    combination doesn't beat the blend out-of-sample, simplicity cost us nothing.

    python exp_joint.py            # disposals
    python exp_joint.py --stat fantasy
"""
import argparse, json, math, os
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import lightgbm as lgb
import matchup as M
import lineups as L

FW = M.FORM_WINDOWS
ENV_CACHE = "env_meta.json"


def env_meta(years):
    """{(season,round,team): {is_home, hour_local, venue, is_night}} from match meta."""
    if os.path.exists(ENV_CACHE):
        raw = json.load(open(ENV_CACHE))
        return {tuple(json.loads(k)): v for k, v in raw.items()}
    token = L.get_token(verify=True)
    out = {}
    for y in years:
        y = int(y)
        cid = L.compseason_id(y, token, True)
        for rnd in range(1, 30):
            ms = L._matches(cid, rnd, token, True)
            for m in ms:
                t = m.get("utcStartTime", "")
                try:
                    hr = (datetime.fromisoformat(t.replace("Z", "+00:00")).hour + 10) % 24  # ~AEST
                except Exception:
                    hr = 14
                ven = (m.get("venue") or {})
                ven = ven.get("name") if isinstance(ven, dict) else str(ven)
                home = L.AFL2CSV.get(m["home"]["team"]["name"], m["home"]["team"]["name"])
                away = L.AFL2CSV.get(m["away"]["team"]["name"], m["away"]["team"]["name"])
                for team, is_home in ((home, 1), (away, 0)):
                    out[(y, rnd, team)] = {"is_home": is_home, "hour": hr,
                                           "venue": ven, "is_night": int(hr >= 18)}
    json.dump({json.dumps(list(k)): v for k, v in out.items()}, open(ENV_CACHE, "w"))
    return out


def _h2h(prior, opp, season, col):
    g = [r for r in prior if r["opponent"] == opp]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (season - 3)) for r in g], float)
    return float((np.array([r[col] for r in g], float) * w).sum() / w.sum())


def build(stat):
    df = pd.read_csv("cba_games.csv")
    for c in ["disposals", "fantasy", "pct_played", "cba_pct", "centre_clearances",
              "ruck_contests", "kickins"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df[stat].notna()].sort_values(["season", "round"]).reset_index(drop=True)
    env = env_meta(sorted(df.season.unique()))

    # opponent disposals-against history
    team_for = df.groupby(["season", "round", "team"])["disposals"].sum().to_dict()
    opp_of = df.groupby(["season", "round", "team"])["opponent"].first().to_dict()
    team_da = defaultdict(list)
    for (s, r, t), o in opp_of.items():
        v = team_for.get((s, r, o))
        if v is not None:
            team_da[t].append((s, r, v))
    for t in team_da:
        team_da[t].sort()

    phist = defaultdict(list)
    rows = []
    for rec in df.to_dict("records"):
        s, r, opp = rec["season"], rec["round"], rec["opponent"]
        key = (rec["player"], rec["team"]); prior = phist[key]
        sp = [x for x in prior if x["season"] == s]
        if len(sp) >= 3:
            d = [x[stat] for x in sp]
            def m_(col, src=sp, n=None):
                v = [x[col] for x in (src[-n:] if n else src) if pd.notna(x[col])]
                return float(np.mean(v)) if v else np.nan
            windows = {f"L{w}": float(np.mean(d[-w:])) for w in FW}
            season_avg = float(np.mean(d))
            h2h = _h2h(prior, opp, s, stat)
            has = pd.notna(h2h)
            blend = M.project(windows, h2h, season_avg, has)
            cba_season = m_("cba_pct"); cba_recent = m_("cba_pct", n=3)
            odh = [v for (ds, dr, v) in team_da[opp] if (ds, dr) < (s, r)]
            e = env.get((s, r, rec["team"]), {})
            rows.append({
                "season": s, "actual": float(rec[stat]), "blend": blend,
                "L3": windows["L3"], "L5": windows["L5"], "L10": windows["L10"],
                "season_avg": season_avg, "h2h": h2h, "vol": float(np.std(d[-10:])),
                "tog_L3": m_("pct_played", n=3), "tog_season": m_("pct_played"),
                "rate_L3": (m_(stat, n=3) / m_("pct_played", n=3)
                            if m_("pct_played", n=3) else np.nan),
                "cba_recent": cba_recent, "cba_trend": (cba_recent - cba_season
                              if pd.notna(cba_recent) and pd.notna(cba_season) else np.nan),
                "cc_L3": m_("centre_clearances", n=3), "ruck_L3": m_("ruck_contests", n=3),
                "kickins_L3": m_("kickins", n=3),
                "opp_da_recent": float(np.mean(odh[-3:])) if len(odh) >= 1 else np.nan,
                "opp_da_season": float(np.mean(odh)) if len(odh) >= 1 else np.nan,
                "is_home": e.get("is_home", np.nan), "is_night": e.get("is_night", np.nan),
                "hour": e.get("hour", np.nan), "round_no": r,
                "venue": e.get("venue"),
            })
        phist[key].append(rec)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat", choices=["disposals", "fantasy"], default="disposals")
    args = ap.parse_args()
    df = build(args.stat)
    df["venue"] = df["venue"].astype("category")
    feats = [c for c in df.columns if c not in ("season", "actual")]

    tr, te = df[df.season == 2025], df[df.season == 2026]
    print(f"\n  COMBINED-MODEL TEST ({args.stat}) — answering BRAINSTORM.md §17/§18")
    print(f"  train {len(tr)} (2025)  ->  test {len(te)} (2026)   {len(feats)} features")
    print(f"  {'-'*58}")

    # honest baseline: the simple blend on the SAME 2026 test games
    mae_blend = float(np.mean(np.abs(te["blend"] - te["actual"])))

    # ensemble: LightGBM over all levers (blend included as a feature). Native API
    # so no scikit-learn dependency. Time-ordered train, last 15% of 2025 as val.
    nval = int(len(tr) * 0.85)
    dtr = lgb.Dataset(tr[feats].iloc[:nval], label=tr["actual"].iloc[:nval])
    dval = lgb.Dataset(tr[feats].iloc[nval:], label=tr["actual"].iloc[nval:], reference=dtr)
    params = {"objective": "mae", "learning_rate": 0.03, "num_leaves": 31,
              "min_child_samples": 60, "feature_fraction": 0.8, "bagging_fraction": 0.8,
              "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1}
    booster = lgb.train(params, dtr, num_boost_round=2000, valid_sets=[dval],
                        callbacks=[lgb.early_stopping(60, verbose=False)])
    pred = booster.predict(te[feats])
    mae_lgb = float(np.mean(np.abs(pred - te["actual"])))

    d = mae_lgb - mae_blend
    print(f"  {'simple blend (baseline)':<30}{mae_blend:>8.3f}")
    print(f"  {'LightGBM ensemble (all levers)':<30}{mae_lgb:>8.3f}   "
          f"({d:+.3f}, {d/mae_blend*100:+.1f}%)   "
          f"{'COMBINING HELPS' if d < -0.02 else 'no real gain'}")
    imp = sorted(zip(booster.feature_name(), booster.feature_importance("gain")),
                 key=lambda x: -x[1])
    print(f"\n  top features the model leaned on (gain):")
    for f, v in imp[:12]:
        print(f"    {f:<16}{v:>10.0f}")


if __name__ == "__main__":
    main()
