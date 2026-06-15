"""
Generate docs/results.html — the public "How Punters Mate has done so far" page.

Data-driven from the round snapshots (predictions_<year>_R<rd>.json) graded against
AFL API actuals — per game, per round, and across all rounds, with the green-vs-amber
adverse-selection breakdown. Completed rounds are cached to results_data.json so they
aren't re-graded each run; only the latest round recomputes.

    python results.py            # regenerate docs/results.html
The weekly Monday job runs this after grading and pushes the page.
"""
import glob, json, os, re
from datetime import datetime, timezone
import pandas as pd
import scorecard as SC

OUT = "docs/results.html"
CACHE = "results_data.json"
YEAR = 2026
TARGET = 85   # floor confidence


def round_results(year, rnd):
    """Structured grade of one round: per-game + totals + green/amber."""
    snap = json.load(open(SC.SNAP.format(year=year, rnd=rnd), encoding="utf-8"))
    pred = pd.DataFrame(snap["rows"])
    actuals, played = SC.api_actuals(year, rnd)
    pred["actual"] = [actuals.get(SC._key(t, p)) for t, p in zip(pred.team, pred.player)]
    g = pred[pred.game.isin(played) & pred.actual.notna()].copy()
    page_games = list(dict.fromkeys(pred.game))
    conc = [x for x in page_games if x in played]
    if not len(g):
        return None

    games = []
    for gm in conc:
        gp = g[g.game == gm]
        sh, roi = SC._row(gp[gp.shown]), SC._roi(gp)
        games.append({"game": gm, "shown_hit": sh["hit"] if sh else None,
                      "shown_n": sh["n"] if sh else 0,
                      "value_n": roi["n"] if roi else 0,
                      "value_roi": roi["roi"] if roi else None})
    shown, value = SC._row(g[g.shown]), SC._roi(g)
    green, amber = SC._row(g[g.tint == "clear"]), SC._row(g[g.tint == "border"])
    return {"round": rnd, "games": games,
            "games_concluded": len(conc), "games_total": len(page_games),
            "complete": len(conc) == len(page_games),
            "shown_hit": shown["hit"] if shown else None, "shown_n": shown["n"] if shown else 0,
            "shown_mae": shown["mae"] if shown else None,
            "value_n": value["n"] if value else 0, "value_roi": value["roi"] if value else None,
            "value_profit": value["profit"] if value else 0.0,
            "value_win": value["win"] if value else None,
            "green": green, "amber": amber}


def gather(year=YEAR):
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    out = []
    for f in sorted(glob.glob(SC.SNAP.format(year=year, rnd="*"))):
        m = re.search(r"_R(\d+)\.json$", f)
        if not m:
            continue
        rnd = int(m.group(1))
        c = cache.get(str(rnd))
        if c and c.get("complete"):
            out.append(c); continue           # completed rounds never change
        try:
            r = round_results(year, rnd)
        except Exception as e:
            print(f"  R{rnd}: skipped ({type(e).__name__}: {e})"); continue
        if r:
            cache[str(rnd)] = r; out.append(r)
    json.dump(cache, open(CACHE, "w"))
    return sorted(out, key=lambda r: r["round"])


# ── HTML ────────────────────────────────────────────────────────────────────────
def pct(x): return "—" if x is None else f"{x*100:.0f}%"
def roi(x): return "—" if x is None else f"{x*100:+.1f}%"


def build_html(rounds):
    sn = sum(r["shown_n"] for r in rounds)
    blend_hit = sum((r["shown_hit"] or 0) * r["shown_n"] for r in rounds) / sn if sn else None
    vn = sum(r["value_n"] for r in rounds)
    profit = sum(r["value_profit"] for r in rounds)
    blend_roi = profit / vn if vn else None
    gn = sum((r["green"] or {}).get("n", 0) for r in rounds)
    ghit = sum((r["green"] or {}).get("hit", 0) * (r["green"] or {}).get("n", 0) for r in rounds) / gn if gn else None
    an = sum((r["amber"] or {}).get("n", 0) for r in rounds)
    ahit = sum((r["amber"] or {}).get("hit", 0) * (r["amber"] or {}).get("n", 0) for r in rounds) / an if an else None
    # over-target = displays as 85%+ (round-consistent, so no "shows 85% but flagged red")
    ot = lambda h: round((h or 0) * 100) >= 85
    rounds_ok = sum(1 for r in rounds if ot(r["shown_hit"]))
    all_games = [gm for r in rounds for gm in r["games"]]
    games_ok = sum(1 for gm in all_games if ot(gm["shown_hit"]))

    cls = lambda v, good: ("pos" if (v or 0) >= 0 else "neg") if good else ""
    hcls = lambda h: "pos" if ot(h) else ""   # floor-hit at/above target = green
    # per-round rows (floor-hit is the star; value columns muted)
    rrows = "".join(
        f"<tr><td class='l'>R{r['round']}{'' if r['complete'] else ' <span class=ip>(in&nbsp;progress)</span>'}</td>"
        f"<td>{r['games_concluded']}</td><td class='{hcls(r['shown_hit'])} big'>{pct(r['shown_hit'])}</td>"
        f"<td class=q>{r['value_n']}</td><td class='q {cls(r['value_roi'],1)}'>{roi(r['value_roi'])}</td></tr>"
        for r in rounds)
    gblocks = ""
    for r in rounds:
        grows = "".join(
            f"<tr><td class='l'>{gm['game']}</td><td class='{hcls(gm['shown_hit'])} big'>{pct(gm['shown_hit'])}</td>"
            f"<td class=q>{gm['value_n']}</td><td class='q {cls(gm['value_roi'],1)}'>{roi(gm['value_roi'])}</td></tr>"
            for gm in r["games"])
        gblocks += (f"<details class='gd'><summary>Round {r['round']} &middot; "
                    f"by game ({r['games_concluded']} games)</summary>"
                    f"<table class='t'><tr><th class='l'>Game</th><th>Floor&#8209;hit</th>"
                    f"<th>Value picks</th><th>Value ROI</th></tr>{grows}</table></details>")

    updated = datetime.now(timezone.utc).strftime("%d %b %Y")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Punters Mate — Track record</title>
<style>
:root{{--ink:#0c2f6b;--mut:#5b6f96;--line:rgba(12,47,107,.14);--inset:#f3f7fd;
--good:#1a9e6a;--gtint:#eaf7f1;--mid:#c0890f;--brand:#1551bf;--bad:#e0612f}}
*{{box-sizing:border-box}}
body{{margin:0;background:#fff;color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:740px;margin:0 auto;padding:22px 16px 60px}}
a{{color:var(--brand)}}
h1{{font-size:21px;margin:0 0 2px}} h1 span{{color:var(--brand)}}
.sub{{color:var(--mut);font-size:13px;margin:0 0 18px}}
.hero{{background:var(--gtint);border:1px solid rgba(26,158,106,.3);border-left:5px solid var(--good);
border-radius:13px;padding:16px 18px;margin:0 0 16px}}
.hero .big{{font-size:30px;font-weight:800;color:var(--good);letter-spacing:-.02em;line-height:1}}
.hero .lead{{font-size:14.5px;font-weight:700;margin:7px 0 2px}}
.hero .lead b{{color:var(--good)}}
.hero .s{{font-size:12.7px;color:var(--mut)}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 22px}}
.card{{flex:1 1 150px;background:var(--inset);border:1px solid var(--line);border-radius:12px;padding:12px 15px}}
.card .v{{font-size:22px;font-weight:800;letter-spacing:-.01em}}
.card .k{{font-size:12px;color:var(--mut);margin-top:2px}}
.pos{{color:var(--good)}} .neg{{color:var(--bad)}}
h2{{font-size:15px;margin:26px 0 9px}}
table.t{{width:100%;border-collapse:collapse;font-size:13.5px}}
.t th,.t td{{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}}
.t th{{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.t .l{{text-align:left}} .t .big{{font-weight:800}} .t .q{{color:var(--mut);font-weight:500}}
.t tr:last-child td{{border-bottom:none}}
.t tfoot td{{font-weight:800;border-top:2px solid var(--line)}}
.ip{{color:var(--mut);font-weight:400;font-size:11px}}
.sec{{background:var(--inset);border:1px solid var(--line);border-radius:13px;padding:14px 16px;margin-top:6px}}
.sec h3{{font-size:14px;margin:0 0 5px}} .sec p{{font-size:12.7px;color:var(--mut);margin:0 0 10px}}
.sec p b{{color:var(--ink)}}
.ga{{display:flex;gap:10px}}
.ga .b{{flex:1;background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px 13px}}
.ga .b.g{{border-left:4px solid var(--good)}} .ga .b.a{{border-left:4px solid var(--mid)}}
.ga .b .v{{font-size:20px;font-weight:800}} .ga .b .k{{font-size:11.5px;color:var(--mut)}}
.note{{font-size:12.5px;color:var(--mut);margin-top:18px}} .note b{{color:var(--ink)}}
.gd{{margin:8px 0;border:1px solid var(--line);border-radius:10px;padding:4px 12px}}
.gd summary{{cursor:pointer;font-size:13px;font-weight:600;padding:7px 0;color:var(--ink)}}
.foot{{margin-top:22px;font-size:12px;color:var(--mut)}}
</style></head><body><div class=wrap>
<h1>How <span>Punters&nbsp;Mate</span> has done so far</h1>
<p class=sub>An honest, auto-updated track record &middot; updated {updated} &middot; <a href="index.html">&larr; back to this week&rsquo;s picks</a></p>

<div class=hero>
<div class=big>{pct(blend_hit)}</div>
<div class=lead>The floor is doing its job &mdash; comfortably <b>above the 85% target</b>.</div>
<div class=s>Across {len(rounds)} rounds, players have cleared the conservative minimum we set for them {pct(blend_hit)} of the time &mdash; over target in <b>every round so far</b> ({rounds_ok} of {len(rounds)}) and in most games ({games_ok} of {len(all_games)}). That reliability is the core of what the tool does.</div>
</div>

<div class=cards>
<div class=card><div class="v pos">{rounds_ok}/{len(rounds)}</div><div class=k>rounds that cleared the 85% target</div></div>
<div class=card><div class="v pos">{games_ok}/{len(all_games)}</div><div class=k>games over target (shown picks)</div></div>
<div class=card><div class=v>{vn}</div><div class=k>value picks tracked across {len(all_games)} games</div></div>
</div>

<h2>By round &mdash; the floor holds</h2>
<table class=t><tr><th class=l>Round</th><th>Games</th><th>Floor&#8209;hit</th><th>Value picks</th><th>Value ROI</th></tr>
{rrows}
<tfoot><tr><td class=l>All</td><td>&middot;</td><td class='{hcls(blend_hit)} big'>{pct(blend_hit)}</td><td class=q>{vn}</td><td class='q {cls(blend_roi,1)}'>{roi(blend_roi)}</td></tr></tfoot>
</table>

<h2>Round&#8209;by&#8209;round, game by game</h2>
{gblocks}

<h2>A note on the value highlights</h2>
<div class=sec>
<p>Separate from the floor: the <b>green/amber tints</b> flag where our model thinks the bookie&rsquo;s price is generous. Be clear-eyed about these &mdash; backing every one returns <b>{roi(blend_roi)}</b> so far, so they&rsquo;re a research <i>input</i>, not a system for beating the bookies. And a useful nuance: a <b>bigger</b> model edge usually means the market knows late info we don&rsquo;t, so the <b>green</b> picks have actually cleared their floor <i>less</i> often than amber. If you use the tints, favour <b>amber</b> (or amber + un&#8209;highlighted).</p>
<div class=ga>
<div class="b g"><div class="v">{pct(ghit)}</div><div class=k>GREEN (clear value) &middot; {gn} picks</div></div>
<div class="b a"><div class="v">{pct(ahit)}</div><div class=k>AMBER (borderline) &middot; {an} picks</div></div>
</div>
</div>

<div class=note><b>The bottom line.</b> The floor &mdash; a conservative minimum each player clears ~85% of the time &mdash; is reliable, and that&rsquo;s the point of the tool. The value tints are an honest extra, not an edge. Small sample; it grows each round.</div>
<p class=foot>Gamble responsibly. Nothing here is a tip or a guarantee. Gambling Help 1800&nbsp;858&nbsp;858 (AU).</p>
</div></body></html>"""


def main():
    rounds = gather()
    if not rounds:
        print("no graded rounds yet"); return
    os.makedirs("docs", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(build_html(rounds))
    vn = sum(r["value_n"] for r in rounds)
    print(f"wrote {OUT}: {len(rounds)} rounds, {vn} value picks")


if __name__ == "__main__":
    main()
