"""
Build a single self-contained HTML app for AFL matchup projections.

Pick a fixtured game from a dropdown (driven by the Squiggle fixture) and the
page renders both teams' projected disposals & goals in-browser. All data is
embedded as JSON, so the file works offline with no server.

Usage:
    python matchup_app.py                         # remaining 2026 fixture, top 10
    python matchup_app.py --out matchups.html --n 12
    python matchup_app.py --insecure              # corporate SSL workaround
"""
import argparse
import json
from datetime import date

import pandas as pd

import matchup as M
import fixtures as F


def _view_to_records(view: pd.DataFrame) -> list[dict]:
    """Round the projection view to plain JSON-friendly records (NaN -> None)."""
    cols = ["player", "GP", "R_n",
            "D_avg", "D_L5", "D_vs", "D_n", "D_proj", "D_floor",
            "G_avg", "G_L5", "G_vs", "G_proj", "G_floor", "G_any"]
    ints = {"GP", "D_n", "R_n", "G_floor"}
    out = []
    for _, r in view[cols].iterrows():
        rec = {}
        for c in cols:
            v = r[c]
            if c == "player":
                rec[c] = str(v)
            elif pd.isna(v):
                rec[c] = None
            elif c in ints:
                rec[c] = int(v)
            else:
                rec[c] = round(float(v), 1)
        out.append(rec)
    return out


def build_games(df: pd.DataFrame, fixture: list[dict], n: int,
                conf: float = M.DEFAULT_CONF):
    """For each fixture game where both clubs have current-season data, attach
    precomputed home/away projection views. Returns (games, skipped)."""
    have = set(df[df.season == M.CURRENT_SEASON]["team"].unique())
    games, skipped = [], []
    for g in fixture:
        home, away = g["home"], g["away"]
        if home not in have or away not in have:
            skipped.append(g)
            continue
        vh = M.team_view(df, home, away, n, conf)
        va = M.team_view(df, away, home, n, conf)
        games.append({
            "round": g["round"], "date": g["date"], "venue": g["venue"],
            "home": home, "away": away,
            "home_view": _view_to_records(vh),
            "away_view": _view_to_records(va),
        })
    return games, skipped


# ── HTML shell (mobile-first; data injected as JSON, rendered in JS) ────────────

_CSS = """
:root{--bg:#0f1419;--card:#1a2027;--inset:#0c1116;--line:#2c3540;--ink:#e6edf3;
      --mut:#8b98a5;--disp:#3b82f6;--goal:#f59e0b;--home:#1f6feb;--away:#d62828;
      --good:#3fb950;--mid:#d4a72c;}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:0 12px 48px}
/* sticky picker so you can switch games while scrolling on a phone */
header.top{position:sticky;top:0;z-index:10;background:var(--bg);
           padding:12px 0 10px;border-bottom:1px solid var(--line)}
h1{font-size:17px;margin:0 0 8px;letter-spacing:.01em}
select{width:100%;background:var(--inset);color:var(--ink);border:1px solid var(--line);
       border-radius:10px;padding:12px 12px;font-size:16px;-webkit-appearance:none;
       appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),
       linear-gradient(135deg,var(--mut) 50%,transparent 50%);
       background-position:calc(100% - 18px) 19px,calc(100% - 13px) 19px;
       background-size:5px 5px,5px 5px;background-repeat:no-repeat}
.meta{color:var(--mut);font-size:12.5px;margin:9px 2px 0}
.sub{color:var(--mut);font-size:12px;margin:10px 2px 14px}
.legend{color:var(--mut);font-size:11.5px;display:flex;gap:6px 14px;flex-wrap:wrap;margin:12px 2px 16px}
.legend b{color:var(--ink)}
.games{display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.card h2{margin:0;padding:12px 15px;font-size:15px;border-bottom:1px solid var(--line);
         display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.card.home h2{border-left:4px solid var(--home)}
.card.away h2{border-left:4px solid var(--away)}
.card h2 small{color:var(--mut);font-weight:400;font-size:12px}
.prow{padding:12px 14px;border-bottom:1px solid var(--line)}
.prow:last-child{border-bottom:none}
.phead{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px}
.pname{font-weight:600;font-size:15px}
.pname .rk{color:var(--mut);font-weight:600;font-size:12px;margin-right:7px}
.pmeta{color:var(--mut);font-size:11.5px;white-space:nowrap}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stat{background:var(--inset);border:1px solid var(--line);border-radius:11px;padding:10px 11px}
.stat .lbl{display:flex;justify-content:space-between;align-items:center;
           font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.stat .big{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.15;
           margin:3px 0 2px}
.stat.disp .big{color:#cfe0ff}.stat.goal .big{color:#ffe2b3}
.stat .big .u{font-size:11px;font-weight:600;color:var(--mut);margin-left:3px}
.proj{display:inline-block;font-size:11px;font-weight:600;color:var(--mut)}
.bar{height:6px;border-radius:99px;background:#222c36;overflow:hidden;margin:7px 0 6px}
.bar>span{display:block;height:100%;border-radius:99px}
.stat.disp .bar>span{background:var(--disp)}.stat.goal .bar>span{background:var(--goal)}
.det{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;
       letter-spacing:.02em}
.badge.yes{background:rgba(63,185,80,.16);color:var(--good);border:1px solid rgba(63,185,80,.4)}
.pct.hi{color:var(--good)}.pct.mid{color:var(--mid)}.pct.lo{color:var(--mut)}
.na{color:#56606b}
.notes{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px;
       color:var(--mut);font-size:12px;margin-top:16px}
.notes h3{color:var(--ink);margin:0 0 8px;font-size:13px}
.notes ul{margin:0;padding-left:18px}.notes li{margin:4px 0}
.chip{display:inline-block;padding:1px 6px;border-radius:99px;font-size:10.5px;
      background:var(--inset);border:1px solid var(--line)}
@media(min-width:780px){
  .wrap{padding:0 20px 60px}
  h1{font-size:22px}
  .games{grid-template-columns:1fr 1fr;align-items:start}
}
@media(max-width:340px){.stats{grid-template-columns:1fr}}
"""

_JS = """
const DATA = __DATA__;
const CONF = Math.round(DATA.conf * 100);
const sel = document.getElementById('game');
const out = document.getElementById('out');
const meta = document.getElementById('meta');

let curRound = null, og = null;
DATA.games.forEach((g, i) => {
  if (g.round !== curRound) {
    curRound = g.round;
    og = document.createElement('optgroup');
    og.label = 'Round ' + g.round;
    sel.appendChild(og);
  }
  const o = document.createElement('option');
  o.value = i;
  o.textContent = g.home + ' v ' + g.away;
  og.appendChild(o);
});

const DASH = '\\u2013', DOT = ' \\u00b7 ';
function f1(v){ return v === null ? DASH : v.toFixed(1); }
function f0(v){ return v === null ? DASH : Math.round(v).toString(); }
function pctCls(p){ return p >= CONF ? 'hi' : (p >= 50 ? 'mid' : 'lo'); }

function dispStat(r, o3, dmax){
  const w = (r.D_proj && dmax) ? Math.max(4, Math.min(100, r.D_proj / dmax * 100)) : 0;
  const det = 'proj ' + f1(r.D_proj) + DOT + 'avg ' + f1(r.D_avg) + DOT +
              'L5 ' + f1(r.D_L5) + DOT + 'v' + o3 + ' ' + f1(r.D_vs) + ' (' + r.D_n + ')';
  return '<div class="stat disp"><div class="lbl"><span>Disposals</span>'+
    '<span>floor \\u00b7 ' + CONF + '%</span></div>'+
    '<div class="big">' + f0(r.D_floor) + '<span class="u">min</span></div>'+
    '<div class="bar"><span style="width:' + w.toFixed(0) + '%"></span></div>'+
    '<div class="det">' + det + '</div></div>';
}
function goalStat(r, o3){
  const any = r.G_any;
  const w = any === null ? 0 : Math.max(2, any);
  const pc = any === null ? 'lo' : pctCls(any);
  const badge = r.G_floor >= 1
      ? ' <span class="badge yes">back ' + r.G_floor + '+</span>' : '';
  const big = any === null ? DASH : Math.round(any) + '%';
  const det = 'proj ' + f1(r.G_proj) + DOT + 'avg ' + f1(r.G_avg) + DOT +
              'L5 ' + f1(r.G_L5) + DOT + 'v' + o3 + ' ' + f1(r.G_vs) + ' (' + r.D_n + ')';
  return '<div class="stat goal"><div class="lbl"><span>Goals</span>'+
    '<span>1+ rate</span></div>'+
    '<div class="big pct ' + pc + '">' + big + badge + '</div>'+
    '<div class="bar"><span style="width:' + w.toFixed(0) + '%"></span></div>'+
    '<div class="det">' + det + '</div></div>';
}
function teamCard(side, team, opp, view){
  const o3 = opp.slice(0, 3);
  const dmax = Math.max(...view.map(r => r.D_proj || 0), 1);
  let rows = '';
  view.forEach((r, i) => {
    rows += '<div class="prow"><div class="phead">'+
      '<div class="pname"><span class="rk">' + (i + 1) + '</span>' + r.player + '</div>'+
      '<div class="pmeta">' + r.GP + ' GP \\u00b7 ' + r.R_n + 'g</div></div>'+
      '<div class="stats">' + dispStat(r, o3, dmax) + goalStat(r, o3) + '</div></div>';
  });
  return '<div class="card ' + side + '"><h2>' + team +
    ' <small>vs ' + opp + '</small></h2>' + rows + '</div>';
}
function render(i){
  const g = DATA.games[i];
  meta.textContent = 'Round ' + g.round + DOT + (g.date || '') + DOT + (g.venue || '');
  out.innerHTML =
    teamCard('home', g.home, g.away, g.home_view) +
    teamCard('away', g.away, g.home, g.away_view);
}
sel.addEventListener('change', e => render(+e.target.value));
if (DATA.games.length) render(0);
"""


def to_html(games, skipped, path, csv, n, conf=M.DEFAULT_CONF):
    cpc = round(conf * 100)
    data = {"generated": str(date.today()), "season": M.CURRENT_SEASON,
            "conf": conf, "games": games}
    payload = json.dumps(data, separators=(",", ":"))
    js = _JS.replace("__DATA__", payload)

    legend = (
        '<div class="legend">'
        f'<span><b>min</b> disposal floor &mdash; hit in &ge;{cpc}% of recent games</span>'
        '<span><b>1+ rate</b> share of recent games with a goal</span>'
        '<span><b class="pct hi">back k+</b> matchup backs &ge;k goals</span>'
        '<span><b>proj</b> blended projection</span>'
        '</div>'
    )
    skip_note = ""
    if skipped:
        names = ", ".join(sorted({t for g in skipped for t in (g["home"], g["away"])}))
        skip_note = (f'<li><b>{len(skipped)}</b> fixtured game(s) hidden &mdash; no '
                     f'current-season data for: {names}.</li>')
    notes = (
        '<div class="notes"><h3>Method &amp; caveats</h3><ul>'
        f'<li><b>Disposal floor</b> &mdash; the {cpc}th-percentile of recent games '
        '(empirical), so the margin scales with each player\'s own volatility. '
        'Capped at the projection.</li>'
        f'<li><b>Goal floor</b> &mdash; largest k with P(&ge;k)&ge;{cpc}% under '
        'Poisson(&lambda;=projection); shown as the green <span class="chip">back k+</span> '
        'badge. <b>1+ rate</b> is the separate empirical scoring reliability.</li>'
        '<li><b>Projection</b> blend &mdash; with H2H: '
        '<span class="chip">0.45&middot;L5 + 0.40&middot;H2H + 0.15&middot;season</span>, '
        'without: <span class="chip">0.75&middot;L5 + 0.25&middot;season</span>; '
        'H2H is recency-weighted (2026 counts 3&times; a 2024 meeting).</li>'
        f'<li>Top {n} players per club by game-time then disposal projection. '
        'Floors use current-season games (recent games across seasons if too few).</li>'
        f'{skip_note}'
        '</ul></div>'
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>AFL Matchup Floors {M.CURRENT_SEASON}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header class="top"><h1>AFL Matchup Floors</h1>
<select id="game" aria-label="Select match"></select>
<p class="meta" id="meta"></p></header>
<p class="sub">Confidence floors for disposals &amp; goals &middot; {cpc}% confidence &middot; \
{M.CURRENT_SEASON} &middot; generated {date.today()} &middot; source: {csv}</p>
{legend}
<div class="games" id="out"></div>
{notes}
</div><script>{js}</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {path}  ({len(games)} games, {len(skipped)} skipped)")


def main():
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2024_2026.csv")
    ap.add_argument("--year", type=int, default=M.CURRENT_SEASON)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--conf", type=float, default=M.DEFAULT_CONF,
                    help="confidence level for floors (0-1, default 0.75)")
    ap.add_argument("--out", default="matchups.html")
    ap.add_argument("--all", action="store_true",
                    help="include completed games from the fixture too")
    ap.add_argument("--fixture", default=None,
                    help="fixture cache JSON; loaded if it exists, else fetched and saved")
    ap.add_argument("--insecure", action="store_true",
                    help="disable SSL verification (corporate networks)")
    args = ap.parse_args()

    df = M.load(args.csv)

    # Stats always come from the static CSV. The fixture is the only live piece,
    # and it can be cached to a local file for fully offline re-runs.
    if args.fixture and os.path.exists(args.fixture):
        with open(args.fixture, encoding="utf-8") as fh:
            fixture = json.load(fh)
        print(f"Loaded fixture from {args.fixture} ({len(fixture)} games)")
    else:
        fixture = F.get_fixtures(args.year, remaining_only=not args.all,
                                 verify=not args.insecure)
        if args.fixture:
            with open(args.fixture, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh)
            print(f"Saved fixture to {args.fixture} ({len(fixture)} games)")

    games, skipped = build_games(df, fixture, args.n, args.conf)
    to_html(games, skipped, args.out, args.csv, args.n, args.conf)


if __name__ == "__main__":
    main()
