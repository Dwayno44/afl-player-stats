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

    cls = lambda v, good: ("pos" if (v or 0) >= 0 else "neg") if good else ""
    # per-round rows
    rrows = "".join(
        f"<tr><td class='l'>R{r['round']}{'' if r['complete'] else ' <span class=ip>(in&nbsp;progress)</span>'}</td>"
        f"<td>{r['games_concluded']}</td><td>{pct(r['shown_hit'])}</td>"
        f"<td>{r['value_n']}</td><td class='{cls(r['value_roi'],1)}'>{roi(r['value_roi'])}</td></tr>"
        for r in rounds)
    # per-game blocks
    gblocks = ""
    for r in rounds:
        grows = "".join(
            f"<tr><td class='l'>{gm['game']}</td><td>{pct(gm['shown_hit'])}</td>"
            f"<td>{gm['value_n']}</td><td class='{cls(gm['value_roi'],1)}'>{roi(gm['value_roi'])}</td></tr>"
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
--good:#1a9e6a;--mid:#c0890f;--brand:#1551bf;--bad:#e0612f}}
*{{box-sizing:border-box}}
body{{margin:0;background:#fff;color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:740px;margin:0 auto;padding:22px 16px 60px}}
a{{color:var(--brand)}}
h1{{font-size:21px;margin:0 0 2px}} h1 span{{color:var(--brand)}}
.sub{{color:var(--mut);font-size:13px;margin:0 0 20px}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 22px}}
.card{{flex:1 1 150px;background:var(--inset);border:1px solid var(--line);border-radius:12px;padding:13px 15px}}
.card .v{{font-size:25px;font-weight:800;letter-spacing:-.01em}}
.card .k{{font-size:12px;color:var(--mut);margin-top:2px}}
.pos{{color:var(--good)}} .neg{{color:var(--bad)}}
h2{{font-size:15px;margin:24px 0 9px}}
table.t{{width:100%;border-collapse:collapse;font-size:13.5px}}
.t th,.t td{{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}}
.t th{{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.t .l{{text-align:left}} .t tr:last-child td{{border-bottom:none}}
.t tfoot td{{font-weight:800;border-top:2px solid var(--line)}}
.ip{{color:var(--mut);font-weight:400;font-size:11px}}
.ga{{display:flex;gap:10px;margin:6px 0 0}}
.ga .b{{flex:1;border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
.ga .b.g{{border-left:4px solid var(--good)}} .ga .b.a{{border-left:4px solid var(--mid)}}
.ga .b .v{{font-size:22px;font-weight:800}} .ga .b .k{{font-size:12px;color:var(--mut)}}
.note{{background:var(--inset);border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:12.7px;color:var(--mut);margin-top:22px}}
.note b{{color:var(--ink)}}
.gd{{margin:8px 0;border:1px solid var(--line);border-radius:10px;padding:4px 12px}}
.gd summary{{cursor:pointer;font-size:13px;font-weight:600;padding:7px 0;color:var(--ink)}}
.foot{{margin-top:24px;font-size:12px;color:var(--mut)}}
</style></head><body><div class=wrap>
<h1>How <span>Punters&nbsp;Mate</span> has done so far</h1>
<p class=sub>An honest, auto-updated track record &middot; updated {updated} &middot; <a href="index.html">&larr; back to this week&rsquo;s picks</a></p>

<div class=cards>
<div class=card><div class=v>{pct(blend_hit)}</div><div class=k>floor&#8209;hit on shown picks <b>(target 85%)</b></div></div>
<div class=card><div class=v>{len(rounds)}</div><div class=k>rounds tracked &middot; {vn} value picks</div></div>
<div class=card><div class="v {cls(blend_roi,1)}">{roi(blend_roi)}</div><div class=k>value&#8209;pick ROI ({profit:+.1f}u staked 1/pick)</div></div>
</div>

<h2>By round</h2>
<table class=t><tr><th class=l>Round</th><th>Games</th><th>Floor&#8209;hit</th><th>Value picks</th><th>Value ROI</th></tr>
{rrows}
<tfoot><tr><td class=l>All</td><td>&middot;</td><td>{pct(blend_hit)}</td><td>{vn}</td><td class='{cls(blend_roi,1)}'>{roi(blend_roi)}</td></tr></tfoot>
</table>

<h2>The catch: our &ldquo;best&rdquo; picks are the worst</h2>
<p class=sub style="margin-bottom:0">Green = biggest model edge. But a big edge usually means the market knows late info we don&rsquo;t (adverse selection) &mdash; so greens clear their floor <b>less</b> often than amber. Favour <b>amber</b>, or amber + un&#8209;highlighted, for reliability.</p>
<div class=ga>
<div class="b g"><div class="v">{pct(ghit)}</div><div class=k>GREEN (clear value) floor&#8209;hit &middot; {gn} picks</div></div>
<div class="b a"><div class="v">{pct(ahit)}</div><div class=k>AMBER (borderline) floor&#8209;hit &middot; {an} picks</div></div>
</div>

<h2>Round&#8209;by&#8209;round, game by game</h2>
{gblocks}

<div class=note><b>How to read this.</b> A <b>floor</b> is a conservative minimum we expect a player to clear ~85% of the time &mdash; and it does (that&rsquo;s the headline number, and it&rsquo;s the honest part). <b>Value picks</b> are where our model disagreed with the bookie&rsquo;s price; <b>value ROI</b> is the return from backing each at its floor. It&rsquo;s usually negative &mdash; this is a research <i>input</i>, not a system for beating the bookies, and we&rsquo;d rather show you that than hide it. Small sample; it grows each round.</div>
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
