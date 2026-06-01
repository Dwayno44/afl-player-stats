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
import os
from datetime import date

import pandas as pd

import matchup as M
import fixtures as F

APPLE_ICON = "apple-touch-icon.png"


def write_apple_icon(out_html_path: str, size: int = 180) -> str:
    """Draw a simple AFL-football home-screen icon next to the output HTML.

    iOS ignores data-URI apple-touch-icons, so we emit a real PNG and reference
    it relatively. Full-bleed dark background since iOS masks the icon to a
    rounded squircle. Returns the relative filename for the <link>."""
    from PIL import Image, ImageDraw

    icon_path = os.path.join(os.path.dirname(os.path.abspath(out_html_path)), APPLE_ICON)
    img = Image.new("RGB", (size, size), (15, 20, 25))      # --bg
    d = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    rw, rh = size * 0.27, size * 0.42
    d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(245, 158, 11))   # footy, --goal amber
    seam = max(3, int(size * 0.022))
    d.line([(cx, cy - rh * 0.72), (cx, cy + rh * 0.72)], fill=(15, 20, 25), width=seam)
    lace = max(2, int(size * 0.012))
    for t in range(-3, 4):
        y = cy + t * rh * 0.155
        d.line([(cx - size * 0.05, y), (cx + size * 0.05, y)], fill=(15, 20, 25), width=lace)
    img.save(icon_path, "PNG")
    return APPLE_ICON


def _view_to_records(view: pd.DataFrame) -> list[dict]:
    """Round the projection view to plain JSON-friendly records (NaN -> None).

    D_proj and D_sigma are sent so the disposal floor can be rebuilt in-browser at
    any confidence level (floor = proj - z(conf)*sigma); sigma keeps 2 dp so the
    floor is exact after the floor()/round-down."""
    cols = ["player", "GP", "R_n",
            "D_avg", "D_L5", "D_vs", "D_n", "D_proj", "D_sigma",
            "G_avg", "G_L5", "G_vs", "G_proj", "G_floor", "G_any"]
    ints = {"GP", "D_n", "R_n", "G_floor"}
    round2 = {"D_sigma"}
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
                rec[c] = round(float(v), 2 if c in round2 else 1)
        out.append(rec)
    return out


def build_games(df: pd.DataFrame, fixture: list[dict],
                conf: float = M.DEFAULT_CONF):
    """For each fixture game where both clubs have current-season data, attach
    precomputed home/away projection views. Every current-season player is
    included (sorted by disposal projection); the page filters by floor in-browser
    so the floor>=10 cut tracks the confidence the user picks. Returns (games, skipped)."""
    have = set(df[df.season == M.CURRENT_SEASON]["team"].unique())
    games, skipped = [], []
    for g in fixture:
        home, away = g["home"], g["away"]
        if home not in have or away not in have:
            skipped.append(g)
            continue
        vh = M.team_view(df, home, away, None, conf)
        va = M.team_view(df, away, home, None, conf)
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
.dial{margin-top:9px}
.dial label{display:block;font-size:11px;letter-spacing:.04em;text-transform:uppercase;
            color:var(--mut);margin:0 2px 5px}
.sub{color:var(--mut);font-size:12px;margin:10px 2px 14px}
.empty{color:var(--mut);font-size:12.5px;padding:14px;font-style:italic}
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
.pct.elite{color:var(--good);font-weight:800}
/* goal floor backs 1+ goals at the confidence level — flag the whole goal cell */
.stat.goal.hot{border-color:rgba(63,185,80,.55);background:rgba(63,185,80,.08)}
.na{color:#56606b}
.notes{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px;
       color:var(--mut);font-size:12px;margin-top:16px}
.notes h3{color:var(--ink);margin:0 0 8px;font-size:13px}
.notes ul{margin:0;padding-left:18px}.notes li{margin:4px 0}
.chip{display:inline-block;padding:1px 6px;border-radius:99px;font-size:10.5px;
      background:var(--inset);border:1px solid var(--line)}
/* betting-strategy panel (collapsible) */
.strategy{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-top:16px}
.strategy>summary{cursor:pointer;padding:14px 17px;font-size:13px;font-weight:600;color:var(--ink);
       list-style:none;display:flex;justify-content:space-between;align-items:center}
.strategy>summary::-webkit-details-marker{display:none}
.strategy>summary::after{content:'\\002b';color:var(--mut);font-weight:700;font-size:16px}
.strategy[open]>summary::after{content:'\\2212'}
.strategy>summary:hover{color:var(--disp)}
.stratbody{padding:0 17px 16px;color:var(--mut);font-size:12.5px}
.stratbody b{color:var(--ink)}
.stratbody ol{margin:4px 0 14px;padding-left:20px}.stratbody li{margin:5px 0}
table.be{width:100%;border-collapse:collapse;margin:4px 0 12px;font-variant-numeric:tabular-nums}
table.be th,table.be td{padding:6px 8px;text-align:right;border-bottom:1px solid var(--line);font-size:12px}
table.be th{color:var(--mut);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
table.be td:first-child,table.be th:first-child{text-align:left}
table.be tr:last-child td{border-bottom:none}
table.be td.be-ok{color:var(--good)}
.caveat{font-size:11px;line-height:1.5;margin:8px 0 0;color:#6b7681}
@media(min-width:780px){
  .wrap{padding:0 20px 60px}
  h1{font-size:22px}
  .games{grid-template-columns:1fr 1fr;align-items:start}
}
@media(max-width:340px){.stats{grid-template-columns:1fr}}
"""

_JS = """
const DATA = __DATA__;
const GCONF = Math.round(DATA.goal_conf * 100);   // goals: fixed (server-side)
// One-sided normal quantiles for the four "mad cunt" disposal confidence levels.
const Z = {90:1.2816, 85:1.0364, 80:0.8416, 75:0.6745};
const FLOOR_MIN = 10;          // only show players whose disposal floor clears this
const sel = document.getElementById('game');
const madcunt = document.getElementById('madcunt');
const out = document.getElementById('out');
const meta = document.getElementById('meta');
let curConf = parseInt(madcunt.value, 10);   // disposal confidence (toggled live)
let curGame = 0;

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
const HOT = 85;   // 1+ goal rate above this is flagged as "very likely"
function f1(v){ return v === null ? DASH : v.toFixed(1); }
function f0(v){ return v === null ? DASH : Math.round(v).toString(); }
function pctCls(p){ return p > HOT ? 'elite' : (p >= GCONF ? 'hi' : (p >= 50 ? 'mid' : 'lo')); }

// Disposal floor rebuilt client-side at the chosen confidence: proj - z*sigma,
// rounded down, never below 0. <3 recent games (sigma null) -> flat 15% haircut.
function dispFloor(r, conf){
  if (r.D_proj === null || r.D_proj === undefined) return null;
  if (r.D_sigma === null) return Math.max(0, Math.floor(r.D_proj * 0.85));
  return Math.max(0, Math.floor(r.D_proj - Z[conf] * r.D_sigma));
}

function dispStat(r, o3, dmax){
  const floor = dispFloor(r, curConf);
  const w = (r.D_proj && dmax) ? Math.max(4, Math.min(100, r.D_proj / dmax * 100)) : 0;
  const det = 'proj ' + f1(r.D_proj) + DOT + 'avg ' + f1(r.D_avg) + DOT +
              'L5 ' + f1(r.D_L5) + DOT + 'v' + o3 + ' ' + f1(r.D_vs) + ' (' + r.D_n + ')';
  return '<div class="stat disp"><div class="lbl"><span>Disposals</span>'+
    '<span>' + curConf + '% conf</span></div>'+
    '<div class="big">' + f0(floor) + '<span class="u">min</span></div>'+
    '<div class="bar"><span style="width:' + w.toFixed(0) + '%"></span></div>'+
    '<div class="det">' + det + '</div></div>';
}
function goalStat(r, o3, gmax){
  const floor = r.G_floor;              // hero: conf% goal floor (k+)
  const any = r.G_any;                  // supporting: empirical 1+ rate
  const backed = floor !== null && floor >= 1;
  const w = (r.G_proj && gmax) ? Math.max(4, Math.min(100, r.G_proj / gmax * 100)) : 0;
  const pc = any === null ? 'lo' : pctCls(any);
  const anyTxt = any === null ? DASH : Math.round(any) + '%';
  const det = 'proj ' + f1(r.G_proj) + DOT + 'avg ' + f1(r.G_avg) + DOT +
              'L5 ' + f1(r.G_L5) + DOT + 'v' + o3 + ' ' + f1(r.G_vs) + ' (' + r.D_n + ')';
  return '<div class="stat goal' + (backed ? ' hot' : '') + '"><div class="lbl"><span>Goals</span>'+
    '<span>' + GCONF + '% conf</span></div>'+
    '<div class="big">' + (floor === null ? DASH : floor) + '<span class="u">+ goals</span></div>'+
    '<div class="bar"><span style="width:' + w.toFixed(0) + '%"></span></div>'+
    '<div class="det"><b class="pct ' + pc + '">' + anyTxt + '</b> 1+ rate' + DOT + det + '</div></div>';
}
function teamCard(side, team, opp, view){
  const o3 = opp.slice(0, 3);
  // Filter to players whose disposal floor clears FLOOR_MIN at the chosen
  // confidence; the cut moves with the toggle (looser conf -> higher floors).
  const shown = view.filter(r => { const f = dispFloor(r, curConf); return f !== null && f >= FLOOR_MIN; });
  if (!shown.length)
    return '<div class="card ' + side + '"><h2>' + team + ' <small>vs ' + opp + '</small></h2>'+
      '<div class="empty">No players clear a ' + FLOOR_MIN + '-disposal floor at ' + curConf + '% confidence.</div></div>';
  const dmax = Math.max(...shown.map(r => r.D_proj || 0), 1);
  const gmax = Math.max(...shown.map(r => r.G_proj || 0), 1);
  let rows = '';
  shown.forEach((r, i) => {
    rows += '<div class="prow"><div class="phead">'+
      '<div class="pname"><span class="rk">' + (i + 1) + '</span>' + r.player + '</div>'+
      '<div class="pmeta">' + r.GP + ' GP \\u00b7 ' + r.R_n + 'g</div></div>'+
      '<div class="stats">' + dispStat(r, o3, dmax) + goalStat(r, o3, gmax) + '</div></div>';
  });
  return '<div class="card ' + side + '"><h2>' + team +
    ' <small>vs ' + opp + '</small></h2>' + rows + '</div>';
}
function render(i){
  curGame = i;
  const g = DATA.games[i];
  meta.textContent = 'Round ' + g.round + DOT + (g.date || '') + DOT + (g.venue || '');
  out.innerHTML =
    teamCard('home', g.home, g.away, g.home_view) +
    teamCard('away', g.away, g.home, g.away_view);
}

// Betting strategy + break-even odds, both driven by the chosen confidence.
// Each leg ~= a player clearing their disposal floor (~conf% of the time), so the
// fair per-leg price is 1/conf; n independent legs need (1/conf)^n.
const BE_LEGS = [1, 2, 3, 4, 6, 8, 10];
function renderStrategy(conf){
  const p = conf / 100;
  document.querySelectorAll('.beConf').forEach(el => { el.textContent = conf; });
  document.getElementById('beThresh').textContent = (1 / p).toFixed(2);
  document.getElementById('subDisp').textContent = conf;
  let rows = '';
  BE_LEGS.forEach(n => {
    const wp = Math.pow(p, n) * 100;
    const be = Math.pow(1 / p, n);
    const tgt = Math.pow(1.05 / p, n);   // +5% edge per leg to justify the variance
    rows += '<tr><td>' + n + (n === 1 ? ' (single)' : '') + '</td>'+
      '<td>' + wp.toFixed(1) + '%</td>'+
      '<td class="be-ok">$' + be.toFixed(2) + '</td>'+
      '<td>$' + tgt.toFixed(2) + '</td></tr>';
  });
  document.getElementById('beBody').innerHTML = rows;
}

sel.addEventListener('change', e => render(+e.target.value));
madcunt.addEventListener('change', e => {
  curConf = parseInt(e.target.value, 10);
  renderStrategy(curConf);
  if (DATA.games.length) render(curGame);
});

renderStrategy(curConf);
// Default to the next game that hasn't started yet (fall back to the first).
const now = new Date();
let start = DATA.games.findIndex(g => g.date && new Date(g.date.replace(' ', 'T')) >= now);
if (start < 0) start = 0;
if (DATA.games.length) { sel.value = start; render(start); }
"""


def to_html(games, skipped, path, csv, conf=M.DEFAULT_CONF, goal_conf=M.GOAL_CONF):
    cpc = round(conf * 100)
    gpc = round(goal_conf * 100)
    data = {"generated": str(date.today()), "season": M.CURRENT_SEASON,
            "conf": conf, "goal_conf": goal_conf, "games": games}
    payload = json.dumps(data, separators=(",", ":"))
    js = _JS.replace("__DATA__", payload)
    icon = write_apple_icon(path)

    # "How much of a mad cunt do you want to be?" dial -- toggles disposal confidence.
    dial = (
        '<div class="dial"><label for="madcunt">how much of a mad cunt do you want to be?</label>'
        '<select id="madcunt" aria-label="Confidence level">'
        '<option value="90">Barely a mad cunt at all (90%)</option>'
        '<option value="85" selected>A bit of a mad cunt (85%)</option>'
        '<option value="80">A proper mad cunt (80%)</option>'
        '<option value="75">A real loose cunt (75%)</option>'
        '</select></div>'
    )

    legend = (
        '<div class="legend">'
        '<span><b>min</b> disposal floor &mdash; projection minus your chosen margin of safety</span>'
        f'<span><b>k+ goals</b> goal floor &mdash; most goals backable at {gpc}% confidence</span>'
        '<span><b class="pct hi">highlighted</b> goal floor backs 1+ goal</span>'
        '<span><b>1+ rate</b> supporting: share of recent games with a goal</span>'
        '<span><b>proj</b> blended projection</span>'
        '</div>'
    )

    # Folded-in betting insight from the singles-vs-multi break-even analysis.
    strategy = (
        '<details class="strategy"><summary>Betting strategy &mdash; singles vs multis</summary>'
        '<div class="caveat">A floor is "<b>clears at <span class="beConf">85</span>%</b>", not '
        '"wins your bet". It only pays if the bookie line sits <b>at or below</b> the floor, and '
        'legs in a same-game multi are <b>correlated</b> &mdash; that correlation only ever helps '
        'the book. Treat each leg as roughly a <span class="beConf">85</span>% shot and price '
        'accordingly.</div>'
        '<p class="rules">For the best outcome over time:</p>'
        '<ol class="rules">'
        '<li><b>Look for singles where the odds are at least $<span id="beThresh">1.18</span></b> '
        '&mdash; that is the fair break-even price for a leg that clears '
        '<span class="beConf">85</span>% of the time. Anything shorter is &minus;EV.</li>'
        '<li><b>Prioritise singles over multis.</b> At fair odds extra legs add only variance, '
        'never expected value; books also shade multi legs below the fair price.</li>'
        '<li><b>If you must multi, fewer legs is better.</b> Each added leg multiplies the price '
        'you need just to break even and widens the swings.</li>'
        '</ol>'
        '<p class="rules">Odds you need at the chosen confidence '
        '(<span class="beConf">85</span>% per leg):</p>'
        '<table class="be"><thead><tr><th>Legs</th><th>Win prob</th>'
        '<th>Break-even odds</th><th>"Worth-it" target</th></tr></thead>'
        '<tbody id="beBody"></tbody></table>'
        '<div class="caveat"><b>Break-even</b> = (1/conf)<sup>legs</sup>; below it you lose long-run. '
        '<b>"Worth-it" target</b> bakes in a ~5% edge per leg (1.05/conf)<sup>legs</sup> to justify '
        'the added variance over singles &mdash; the gap widens fast, so big multis need generous '
        'mispricing on every leg, which is rare.</div>'
        '</details>'
    )

    skip_note = ""
    if skipped:
        names = ", ".join(sorted({t for g in skipped for t in (g["home"], g["away"])}))
        skip_note = (f'<li><b>{len(skipped)}</b> fixtured game(s) hidden &mdash; no '
                     f'current-season data for: {names}.</li>')
    notes = (
        '<div class="notes"><h3>Method &amp; caveats</h3><ul>'
        '<li><b>Disposal floor</b> &mdash; the projection minus a margin of safety '
        '(z<sub>conf</sub> &times; the player\'s recent std-dev), so erratic players are '
        'discounted more. Under a normal approximation they clear it in about the chosen '
        'confidence% of games. The dial above sets that confidence live.</li>'
        f'<li><b>Goal floor</b> (hero) &mdash; the largest k with P(&ge;k)&ge;{gpc}% under '
        'Poisson(&lambda;=projection), shown as <span class="chip">k+ goals</span>; the cell '
        f'is highlighted when the floor backs 1+ goal at {gpc}%. <b>1+ rate</b> is a supporting '
        'figure &mdash; the separate empirical share of recent games with a goal. Goals stay at '
        f'{gpc}% regardless of the disposal dial.</li>'
        '<li><b>Projection</b> blend (backtest-tuned, season-anchored) &mdash; recent form '
        'is split across three windows (L3/L5/L10). With H2H: '
        '<span class="chip">0.65&middot;season + 0.15&middot;L3 + 0.05&middot;L5 + 0.05&middot;L10 + 0.10&middot;H2H</span>, '
        'without: <span class="chip">0.55&middot;season + 0.15&middot;L3 + 0.05&middot;L5 + 0.25&middot;L10</span>; '
        'H2H is recency-weighted (2026 counts 3&times; a 2024 meeting).</li>'
        '<li>Every current-season player is shown, sorted by disposal projection, '
        '<b>filtered to a disposal floor of at least 10</b> at the chosen confidence. '
        'Floors use current-season games (recent games across seasons if too few).</li>'
        f'{skip_note}'
        '</ul></div>'
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Punters Mate {M.CURRENT_SEASON}</title>
<link rel="apple-touch-icon" sizes="180x180" href="{icon}">
<link rel="icon" href="{icon}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Punters Mate">
<style>{_CSS}</style></head>
<body><div class="wrap">
<header class="top"><h1>Punters Mate</h1>
<select id="game" aria-label="Select match"></select>
{dial}
<p class="meta" id="meta"></p></header>
<p class="sub">Confidence floors &middot; disposals <span id="subDisp">{cpc}</span>% &middot; goals {gpc}% &middot; \
{M.CURRENT_SEASON} &middot; generated {date.today()} &middot; source: {csv}</p>
{legend}
<div class="games" id="out"></div>
{strategy}
{notes}
</div><script>{js}</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {path}  ({len(games)} games, {len(skipped)} skipped)")


def main():
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    ap.add_argument("--year", type=int, default=M.CURRENT_SEASON)
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

    games, skipped = build_games(df, fixture, args.conf)
    to_html(games, skipped, args.out, args.csv, args.conf)


if __name__ == "__main__":
    main()
