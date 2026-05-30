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
    python matchup.py --csv games_2024_2026.csv
"""
import argparse
import math
from statistics import NormalDist

import numpy as np
import pandas as pd

CURRENT_SEASON = 2026

# Projection weights — season average anchors the projection; recent form is spread
# across three windows (L3/L5/L10) and head-to-head is a minor adjustment. Chosen by
# walk-forward backtest with 5-fold CV (see backtest.py): season-heavy weights minimise
# out-of-sample MAE. The form windows are collinear, so the backtest assigns only a small
# combined weight to them — L10 carries most of the "recent form" signal and L5 the least
# (its CV-optimal weight is ~0; a small floor is kept so all three windows contribute).
FORM_WINDOWS  = (3, 5, 10)   # recent-form averages, each a separately-weighted feature
W_WITH_H2H    = {"L3": 0.15, "L5": 0.05, "L10": 0.05, "h2h": 0.10, "season": 0.65}
W_WITHOUT_H2H = {"L3": 0.15, "L5": 0.05, "L10": 0.25, "season": 0.55}
FORM_GAMES    = 5      # window shown as "L5" in the views (the projection uses all of FORM_WINDOWS)
FLOOR_GAMES   = 15     # recent-game sample used to estimate confidence floors
DEFAULT_CONF  = 0.75   # target confidence for the disposal floor (75%)
GOAL_CONF     = 0.65   # goals are sparse; a 75% Poisson floor is too strict, so
                       # the goal floor uses a lower confidence (a proj of ~1.05
                       # goals clears 1+ here, vs ~1.39 at 75%)


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


def form_means(g: pd.DataFrame, col: str, windows=FORM_WINDOWS) -> dict:
    """{f'L{w}': mean of the player's last w games (this season)} for each window.
    Early in the season a window simply averages the games available."""
    s = g.sort_values("round")[col]
    return {f"L{w}": (s.tail(w).mean() if len(s) else float("nan")) for w in windows}


# ── Confidence floors ───────────────────────────────────────────────────────────
# The disposal floor is the *projection minus a margin of safety*. The margin is
# volatility-scaled (z(conf) * sigma of recent games), so erratic players are
# discounted more, and under a normal approximation the player clears the floor in
# ~conf of games. It is anchored on the matchup-aware projection, not the raw
# recent distribution.

def recent_for_team(df: pd.DataFrame, team: str, player: str,
                    n: int = FLOOR_GAMES, min_n: int = 8) -> pd.DataFrame:
    """Games used for the floor estimate: current season if it has enough
    games (>= min_n), otherwise the most recent `n` games across seasons.
    Anchoring on the current season keeps floors aligned with the player's
    present role rather than blending in stale form."""
    g = df[(df.team == team) & (df.player == player)].sort_values(["season", "round"])
    cur = g[g.season == CURRENT_SEASON]
    if len(cur) >= min_n:
        return cur.tail(n)
    return g.tail(max(n, min_n))


def disposal_floor(proj: float, series: pd.Series, conf: float = DEFAULT_CONF) -> float:
    """Projected disposals minus a volatility-scaled margin of safety.

    margin = z(conf) * sigma, where sigma is the std of the player's recent games
    and z(conf) is the one-sided normal quantile (conf=0.75 -> z~0.67). Under a
    normal approximation the player clears `proj - margin` in ~conf of games.
    Rounded down; never below 0. With <3 games to gauge spread, falls back to a
    flat 15% haircut on the projection."""
    if proj is None or pd.isna(proj):
        return float("nan")
    s = series.dropna()
    if len(s) < 3:
        return float(max(0.0, np.floor(proj * 0.85)))
    sigma = float(s.std(ddof=1))
    margin = NormalDist().inv_cdf(conf) * sigma
    return float(max(0.0, np.floor(proj - margin)))


def goal_floor(proj: float, conf: float = DEFAULT_CONF) -> int:
    """Minimum goals we can back at `conf` confidence, modelling goals as
    Poisson(lambda = projection). Returns the largest k with P(X >= k) >= conf.
    Goals are sparse counts and the head-to-head sample is thin, so a model on
    the matchup-aware projection is more reliable than an empirical percentile.
    (Poisson(1.7) gives P(>=1) ~= 0.82, matching the usual ">1.7 -> back 1" rule.)"""
    if proj is None or pd.isna(proj) or proj <= 0:
        return 0
    lam = float(proj)
    k = 0
    while k < 10:
        cdf, term = 0.0, math.exp(-lam)        # P(X <= k)
        for i in range(k + 1):
            if i:
                term *= lam / i
            cdf += term
        if 1.0 - cdf >= conf:                  # P(X >= k+1) >= conf
            k += 1
        else:
            break
    return k


def anytime_goal_pct(series: pd.Series) -> float:
    """Share of recent games with at least one goal (0..100)."""
    s = series.dropna()
    return float((s >= 1).mean() * 100) if len(s) else float("nan")


def h2h_weighted(vg: pd.DataFrame, col: str) -> float:
    """Recency-weighted head-to-head average (recent meetings count more)."""
    if not len(vg):
        return float("nan")
    w = (vg["season"] - (CURRENT_SEASON - 3)).clip(lower=1)   # 2024->1, 2025->2, 2026->3
    return (vg[col] * w).sum() / w.sum()


def project(forms: dict, h2h, season, has_h2h):
    """Weighted blend of the form windows (L3/L5/L10), head-to-head and season
    average. `forms` maps each window key to its average; season anchors the blend."""
    if has_h2h and pd.notna(h2h):
        w = W_WITH_H2H
        return sum(w[k] * forms[k] for k in forms) + w["h2h"] * h2h + w["season"] * season
    w = W_WITHOUT_H2H
    return sum(w[k] * forms[k] for k in forms) + w["season"] * season


def team_view(df: pd.DataFrame, team: str, opponent: str, n: int,
              conf: float = DEFAULT_CONF, goal_conf: float = GOAL_CONF) -> pd.DataFrame:
    cur = df[(df.team == team) & (df.season == CURRENT_SEASON)]
    vs  = df[(df.team == team) & (df.opponent == opponent)]   # all seasons

    rows = []
    for player, g in cur.groupby("player"):
        gp = g["round"].nunique()
        vg = vs[vs.player == player]
        d_forms = form_means(g, "disposals")
        g_forms = form_means(g, "goals")
        d_avg, d_l5 = g["disposals"].mean(), d_forms["L5"]
        g_avg, g_l5 = g["goals"].mean(),     g_forms["L5"]
        d_vs = h2h_weighted(vg, "disposals")
        g_vs = h2h_weighted(vg, "goals")
        has = len(vg) >= 1

        # Confidence floors from the player's recent games for this club.
        recent = recent_for_team(df, team, player)
        d_proj = project(d_forms, d_vs, d_avg, has)
        g_proj = project(g_forms, g_vs, g_avg, has)
        # Floor = projection minus a volatility-scaled margin of safety.
        d_floor = disposal_floor(d_proj, recent["disposals"], conf)
        rows.append({
            "player": player, "GP": gp, "R_n": len(recent),
            "D_avg": d_avg, "D_L5": d_l5, "D_vs": d_vs, "D_n": len(vg),
            "D_proj": d_proj, "D_floor": d_floor,
            "G_avg": g_avg, "G_L5": g_l5, "G_vs": g_vs,
            "G_proj": g_proj,
            "G_floor": goal_floor(g_proj, goal_conf),
            "G_any": anytime_goal_pct(recent["goals"]),
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


# ── HTML report ────────────────────────────────────────────────────────────────

def _bar(value: float, vmax: float, kind: str) -> str:
    """A small horizontal bar cell: number + proportional fill."""
    if pd.isna(value):
        return '<span class="na">–</span>'
    pct = 0 if not vmax else max(4, min(100, value / vmax * 100))
    return (f'<div class="bar {kind}"><span class="fill" style="width:{pct:.0f}%"></span>'
            f'<span class="val">{value:.1f}</span></div>')


def _team_table(view: pd.DataFrame, opponent: str) -> str:
    d_max = view["D_proj"].max()
    g_max = max(view["G_proj"].max(), 0.1)
    opp = opponent[:3]
    head = (
        "<tr>"
        "<th class='l'>Player</th><th>GP</th>"
        "<th>Avg26</th><th>L5</th><th>v" + opp + "</th><th class='n'>n</th>"
        "<th class='proj'>DISP&nbsp;PROJ</th>"
        "<th>Avg26</th><th>L5</th><th>v" + opp + "</th>"
        "<th class='proj'>GOAL&nbsp;PROJ</th>"
        "</tr>"
    )
    body = []
    for _, r in view.iterrows():
        n = int(r["D_n"])
        ncls = "n0" if n == 0 else ("n1" if n == 1 else "nok")
        fmt = lambda v: "–" if pd.isna(v) else f"{v:.1f}"
        body.append(
            "<tr>"
            f"<td class='l'>{r['player']}</td><td>{int(r['GP'])}</td>"
            f"<td>{fmt(r['D_avg'])}</td><td>{fmt(r['D_L5'])}</td><td>{fmt(r['D_vs'])}</td>"
            f"<td class='n {ncls}'>{n}</td>"
            f"<td class='proj'>{_bar(r['D_proj'], d_max, 'disp')}</td>"
            f"<td>{fmt(r['G_avg'])}</td><td>{fmt(r['G_L5'])}</td><td>{fmt(r['G_vs'])}</td>"
            f"<td class='proj'>{_bar(r['G_proj'], g_max, 'goal')}</td>"
            "</tr>"
        )
    return f"<table>{head}{''.join(body)}</table>"


def to_html(home, away, view_home, view_away, path, csv, n):
    from datetime import date
    css = """
    :root{--bg:#0f1419;--card:#1a2027;--line:#2c3540;--ink:#e6edf3;--mut:#8b98a5;
          --disp:#3b82f6;--goal:#f59e0b;--home:#1f6feb;--away:#d62828;}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--ink);
         font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
    .wrap{max-width:1080px;margin:0 auto;padding:32px 20px 60px}
    h1{font-size:26px;margin:0 0 4px}
    .sub{color:var(--mut);margin:0 0 26px;font-size:13px}
    .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
          margin:0 0 26px;overflow:hidden}
    .card h2{margin:0;padding:14px 18px;font-size:17px;border-bottom:1px solid var(--line)}
    .card.home h2{border-left:4px solid var(--home)}
    .card.away h2{border-left:4px solid var(--away)}
    .card h2 small{color:var(--mut);font-weight:400;font-size:13px}
    table{width:100%;border-collapse:collapse}
    th,td{padding:7px 10px;text-align:right;font-variant-numeric:tabular-nums;
          border-bottom:1px solid var(--line)}
    th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
    td{font-size:13px}
    .l{text-align:left}
    tr:last-child td{border-bottom:none}
    tbody tr:hover td,table tr:hover td{background:#212a33}
    .proj{width:150px}
    .bar{position:relative;height:22px;border-radius:5px;background:#0c1116;overflow:hidden}
    .bar .fill{position:absolute;inset:0;border-radius:5px;opacity:.35}
    .bar.disp .fill{background:var(--disp)} .bar.goal .fill{background:var(--goal)}
    .bar .val{position:relative;display:block;padding-right:8px;line-height:22px;font-weight:600}
    .n0{color:#6b7681} .n1{color:#c9a227} .nok{color:var(--ink)}
    .na{color:#56606b}
    .legend{color:var(--mut);font-size:12px;display:flex;gap:18px;flex-wrap:wrap;margin:0 0 22px}
    .legend b{color:var(--ink)}
    .notes{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;
           color:var(--mut);font-size:12.5px}
    .notes h3{color:var(--ink);margin:0 0 8px;font-size:13px}
    .notes li{margin:3px 0}
    .chip{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
          background:#0c1116;border:1px solid var(--line)}
    """
    legend = (
        '<div class="legend">'
        '<span><b>Avg26</b> season average</span>'
        '<span><b>L5</b> last 5 games (form)</span>'
        f'<span><b>v{home[:3]}/{away[:3]}</b> recency-weighted head-to-head</span>'
        '<span><b>n</b> H2H games (<span class="n1">amber</span>=1, '
        '<span class="n0">grey</span>=0)</span>'
        '<span><b>PROJ</b> blended projection</span>'
        '</div>'
    )
    notes = (
        '<div class="notes"><h3>Method &amp; caveats</h3><ul>'
        '<li>Projection blend (backtest-tuned, season-anchored) &mdash; with H2H history: '
        '<span class="chip">0.65&middot;season + 0.15&middot;L3 + 0.05&middot;L5 + 0.05&middot;L10 + 0.10&middot;H2H</span>; '
        'without: <span class="chip">0.55&middot;season + 0.15&middot;L3 + 0.05&middot;L5 + 0.25&middot;L10</span>.</li>'
        '<li>Head-to-head is <b>recency-weighted</b> (2026 meetings count 3&times; a 2024 one).</li>'
        '<li>Blank goal cells in the source are treated as <b>0</b>, not missing.</li>'
        '<li>H2H samples are small (1&ndash;3 games) &mdash; trust the projection less when '
        '<span class="n0">n&nbsp;is&nbsp;low</span>.</li>'
        f'<li>Players ranked by game-time then disposal projection; top {n} shown per club.</li>'
        '</ul></div>'
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{home} v {away} — Projections</title><style>{css}</style></head>
<body><div class="wrap">
<h1>{home} <span style="color:var(--mut)">vs</span> {away}</h1>
<p class="sub">Projected disposals &amp; goals &middot; generated {date.today()} &middot; source: {csv}</p>
{legend}
<div class="card home"><h2>{home} <small>&mdash; vs {away}</small></h2>{_team_table(view_home, away)}</div>
<div class="card away"><h2>{away} <small>&mdash; vs {home}</small></h2>{_team_table(view_away, home)}</div>
{notes}
</div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2024_2026.csv")
    ap.add_argument("--home", default="Geelong")
    ap.add_argument("--away", default="Carlton")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--html", nargs="?", const="matchup.html", default=None,
                    help="Write an HTML report (default file: matchup.html)")
    args = ap.parse_args()

    df = load(args.csv)
    vh = team_view(df, args.home, args.away, args.n)
    va = team_view(df, args.away, args.home, args.n)
    render(vh, args.home, args.away)
    render(va, args.away, args.home)
    if args.html:
        to_html(args.home, args.away, vh, va, args.html, args.csv, args.n)


if __name__ == "__main__":
    main()
