"""
Matchup projection view from a per-game stats CSV (output of `afltables games`).

For tonight's fixture it shows, per player, for disposals and goals:
  - Avg26 : current-season average
  - L5    : average over their last 5 games this season (recent form)
  - vsOpp : average in games against tonight's opponent (2024-26) + sample size
  - Proj  : a blended projection

Usage:
    python matchup.py                      # Geelong vs Carlton, top 10 each
    python matchup.py --home Carlton --away Geelong --n 12
    python matchup.py --csv games_2024_2026_gee_car.csv
"""
import argparse
import pandas as pd

CURRENT_SEASON = 2026

# Projection weights — emphasise head-to-head + recent form over season-long history.
W_WITH_H2H    = {"form": 0.45, "h2h": 0.40, "season": 0.15}
W_WITHOUT_H2H = {"form": 0.75, "season": 0.25}
FORM_GAMES    = 5     # "recent form" window (most recent games this season)


def load(csv: str) -> pd.DataFrame:
    df = pd.read_csv(csv)
    df["disposals"] = pd.to_numeric(df["disposals"], errors="coerce")
    df["round"]     = pd.to_numeric(df["round"], errors="coerce")
    # On afltables a blank goals cell means zero goals, not missing data.
    df["goals"]     = pd.to_numeric(df["goals"], errors="coerce").fillna(0)
    return df


def last_n_mean(g: pd.DataFrame, col: str, n: int = FORM_GAMES) -> float:
    s = g.sort_values("round").tail(n)[col]
    return s.mean() if len(s) else float("nan")


def h2h_weighted(vg: pd.DataFrame, col: str) -> float:
    """Recency-weighted head-to-head average (recent meetings count more)."""
    if not len(vg):
        return float("nan")
    w = (vg["season"] - (CURRENT_SEASON - 3)).clip(lower=1)   # 2024->1, 2025->2, 2026->3
    return (vg[col] * w).sum() / w.sum()


def project(form, h2h, season, has_h2h):
    """Weighted blend: recent form + head-to-head dominate; season is a stabiliser."""
    if has_h2h and pd.notna(h2h):
        w = W_WITH_H2H
        return w["form"] * form + w["h2h"] * h2h + w["season"] * season
    w = W_WITHOUT_H2H
    return w["form"] * form + w["season"] * season


def team_view(df: pd.DataFrame, team: str, opponent: str, n: int) -> pd.DataFrame:
    cur = df[(df.team == team) & (df.season == CURRENT_SEASON)]
    vs  = df[(df.team == team) & (df.opponent == opponent)]   # all seasons

    rows = []
    for player, g in cur.groupby("player"):
        gp = g["round"].nunique()
        vg = vs[vs.player == player]
        d_avg, d_l5 = g["disposals"].mean(), last_n_mean(g, "disposals")
        g_avg, g_l5 = g["goals"].mean(),     last_n_mean(g, "goals")
        d_vs = h2h_weighted(vg, "disposals")
        g_vs = h2h_weighted(vg, "goals")
        has = len(vg) >= 1
        rows.append({
            "player": player, "GP": gp,
            "D_avg": d_avg, "D_L5": d_l5, "D_vs": d_vs, "D_n": len(vg),
            "D_proj": project(d_l5, d_vs, d_avg, has),
            "G_avg": g_avg, "G_L5": g_l5, "G_vs": g_vs,
            "G_proj": project(g_l5, g_vs, g_avg, has),
        })

    out = pd.DataFrame(rows)
    # "Key" players: most game time this season, then highest disposal projection.
    out = out.sort_values(["GP", "D_proj"], ascending=False).head(n)
    return out.sort_values("D_proj", ascending=False).reset_index(drop=True)


def render(df: pd.DataFrame, team: str, opponent: str) -> None:
    show = df.copy()
    for c in ["D_avg", "D_L5", "D_vs", "D_proj", "G_avg", "G_L5", "G_vs", "G_proj"]:
        show[c] = show[c].round(1)
    show = show.rename(columns={
        "D_avg": "Disp Avg26", "D_L5": "Disp L5", "D_vs": f"Disp v{opponent[:3]}",
        "D_n": "n", "D_proj": "Disp PROJ",
        "G_avg": "Goal Avg26", "G_L5": "Goal L5", "G_vs": f"Goal v{opponent[:3]}",
        "G_proj": "Goal PROJ",
    })
    cols = ["player", "GP",
            "Disp Avg26", "Disp L5", f"Disp v{opponent[:3]}", "n", "Disp PROJ",
            "Goal Avg26", "Goal L5", f"Goal v{opponent[:3]}", "Goal PROJ"]
    print(f"\n{'='*92}\n  {team}  (vs {opponent})   — projected disposals & goals\n{'='*92}")
    print(show[cols].to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2024_2026_gee_car.csv")
    ap.add_argument("--home", default="Geelong")
    ap.add_argument("--away", default="Carlton")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()

    df = load(args.csv)
    render(team_view(df, args.home, args.away, args.n), args.home, args.away)
    render(team_view(df, args.away, args.home, args.n), args.away, args.home)


if __name__ == "__main__":
    main()
