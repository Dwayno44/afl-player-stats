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
import math
import os
from datetime import date, datetime
from statistics import NormalDist

import pandas as pd

import matchup as M
import fixtures as F
import lineups as L
import sportsbet_odds as SB
import forum_sentiment as FS

ICON_SVG = "punters-mate-icon.svg"      # vector favicon / logo (shipped as-is)
APPLE_ICON = "apple-touch-icon.png"     # iOS home screen (180)
ICON_512 = "icon-512.png"               # PWA / Android maskable
MANIFEST = "site.webmanifest"

# The production icon (1024 canvas). Kept here so a build emits every asset it
# references, wherever --out points. Mirrors docs/punters-mate-icon.svg.
_ICON_SVG_SRC = """<svg width="1024" height="1024" viewBox="0 0 1024 1024" role="img" xmlns="http://www.w3.org/2000/svg">
  <title>Punters Mate app icon</title>
  <defs>
    <clipPath id="iconClip"><rect x="0" y="0" width="1024" height="1024" rx="230"/></clipPath>
    <radialGradient id="meshBlue" cx="30%" cy="22%" r="95%">
      <stop offset="0%" stop-color="#3D8BFF"/><stop offset="45%" stop-color="#1A63DC"/>
      <stop offset="100%" stop-color="#082E86"/>
    </radialGradient>
    <linearGradient id="topGlow" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.22"/>
      <stop offset="35%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="ballSheen" x1="0" y1="0" x2="0.5" y2="1">
      <stop offset="0%" stop-color="#ffffff"/><stop offset="60%" stop-color="#f2f5fb"/>
      <stop offset="100%" stop-color="#dde6f4"/>
    </linearGradient>
    <filter id="ballShadow" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="14" stdDeviation="20" flood-color="#041d54" flood-opacity="0.45"/>
    </filter>
  </defs>
  <g clip-path="url(#iconClip)">
    <rect x="0" y="0" width="1024" height="1024" fill="url(#meshBlue)"/>
    <rect x="0" y="0" width="1024" height="1024" fill="url(#topGlow)"/>
    <!-- scale the goal+ball composition up about the centre so it reads at icon sizes -->
    <g transform="translate(512 512) scale(1.3) translate(-512 -512)">
    <line x1="328" y1="430" x2="328" y2="760" stroke="#ffffff" stroke-width="22" stroke-linecap="round" opacity="0.26"/>
    <line x1="696" y1="430" x2="696" y2="760" stroke="#ffffff" stroke-width="22" stroke-linecap="round" opacity="0.26"/>
    <line x1="426" y1="300" x2="426" y2="760" stroke="#ffffff" stroke-width="27" stroke-linecap="round" opacity="0.34"/>
    <line x1="598" y1="300" x2="598" y2="760" stroke="#ffffff" stroke-width="27" stroke-linecap="round" opacity="0.34"/>
    <path d="M376 788 Q472 612 530 532" fill="none" stroke="#ffffff" stroke-width="17"
          stroke-linecap="round" stroke-dasharray="6 52" opacity="0.95"/>
    <g filter="url(#ballShadow)">
      <ellipse cx="530" cy="470" rx="128" ry="184" fill="url(#ballSheen)" transform="rotate(22 530 470)"/>
    </g>
    <g transform="rotate(22 530 470)">
      <ellipse cx="530" cy="470" rx="128" ry="184" fill="none" stroke="#c2d2ec" stroke-width="4"/>
      <ellipse cx="488" cy="400" rx="48" ry="76" fill="#ffffff" opacity="0.6"/>
      <line x1="530" y1="312" x2="530" y2="628" stroke="#0C3FA5" stroke-width="11" stroke-linecap="round"/>
      <line x1="498" y1="402" x2="562" y2="402" stroke="#0C3FA5" stroke-width="9" stroke-linecap="round"/>
      <line x1="498" y1="470" x2="562" y2="470" stroke="#0C3FA5" stroke-width="9" stroke-linecap="round"/>
      <line x1="498" y1="538" x2="562" y2="538" stroke="#0C3FA5" stroke-width="9" stroke-linecap="round"/>
    </g>
    </g>
  </g>
</svg>
"""


def _render_icon(S: int):
    """Reproduce ICON_SVG (AFL ball through the goals on a blue mesh) with PIL,
    rendered at S px. We can't rasterise the SVG (no cairo/rsvg on this box), so
    this mirrors the SVG's 1024-canvas geometry; callers supersample + downscale
    for clean edges. iOS/Android need PNG (they ignore SVG home-screen icons)."""
    import math
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    k = S / 1024.0

    def s(v):
        return v * k

    # ── radial mesh-blue background ──
    cx, cy, rr = 0.30 * S, 0.22 * S, 0.95 * S
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    t = np.clip(np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / rr, 0.0, 1.0)
    c0 = np.array([0x3D, 0x8B, 0xFF], np.float32)
    c1 = np.array([0x1A, 0x63, 0xDC], np.float32)
    c2 = np.array([0x08, 0x2E, 0x86], np.float32)
    a = (t / 0.45)[..., None]
    b = ((t - 0.45) / 0.55)[..., None]
    col = np.where(t[..., None] <= 0.45, c0 * (1 - a) + c1 * a, c1 * (1 - b) + c2 * b)
    img = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    # ── top sheen (white .22 -> 0 over the top 35%) ──
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    h = max(1, int(0.35 * S))
    for y in range(h):
        gd.line([(0, y), (S, y)], fill=(255, 255, 255, int(0.22 * 255 * (1 - y / h))))
    img = Image.alpha_composite(img, glow)

    # ── goal apparatus + motion arc (own layer for true opacity) ──
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)

    def vpost(x, y1, y2, w, op):
        c = (255, 255, 255, int(op * 255))
        r = s(w) / 2
        od.line([(s(x), s(y1)), (s(x), s(y2))], fill=c, width=max(1, round(s(w))))
        for y in (y1, y2):  # round caps
            od.ellipse([s(x) - r, s(y) - r, s(x) + r, s(y) + r], fill=c)

    vpost(328, 430, 760, 22, 0.26)
    vpost(696, 430, 760, 22, 0.26)
    vpost(426, 300, 760, 27, 0.34)
    vpost(598, 300, 760, 27, 0.34)

    # dotted flight path along the quadratic bezier, dash 6 / gap 52
    P0, P1, P2 = (376, 788), (472, 612), (530, 532)
    pts = []
    for i in range(401):
        u = i / 400
        bx = (1 - u) ** 2 * P0[0] + 2 * (1 - u) * u * P1[0] + u * u * P2[0]
        by = (1 - u) ** 2 * P0[1] + 2 * (1 - u) * u * P1[1] + u * u * P2[1]
        pts.append((bx, by))
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.dist(pts[i], pts[i - 1]))
    total, period, r = cum[-1], 6.0 + 52.0, s(17) / 2
    dist = 0.0
    j = 0
    while dist < total:
        while j < len(cum) - 1 and cum[j] < dist:
            j += 1
        px, py = pts[j]
        od.ellipse([s(px) - r, s(py) - r, s(px) + r, s(py) + r], fill=(255, 255, 255, 242))
        dist += period
    fg = ov  # foreground (posts/arc, then shadow + ball); scaled up before compositing

    # ── ball (built upright, then rotated 22° clockwise about its centre) ──
    bx, by, rx, ry = 530, 470, 128, 184
    top, bot = by - ry, by + ry
    # vertical sheen gradient across the ball bbox
    grad = np.empty((S, 3), np.float32)
    w0 = np.array([255, 255, 255], np.float32)
    w1 = np.array([0xF2, 0xF5, 0xFB], np.float32)
    w2 = np.array([0xDD, 0xE6, 0xF4], np.float32)
    for y in range(S):
        f = np.clip((y / k - top) / (bot - top), 0.0, 1.0)
        grad[y] = w0 + (w1 - w0) * (f / 0.6) if f <= 0.6 else w1 + (w2 - w1) * ((f - 0.6) / 0.4)
    grad_img = Image.fromarray(np.repeat(np.clip(grad, 0, 255).astype(np.uint8)[:, None, :], S, axis=1), "RGB")

    ball = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bm = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bm).ellipse([s(bx - rx), s(top), s(bx + rx), s(bot)], fill=255)
    ball.paste(grad_img, (0, 0), bm)
    bd = ImageDraw.Draw(ball)
    bd.ellipse([s(bx - rx), s(top), s(bx + rx), s(bot)], outline=(0xC2, 0xD2, 0xEC, 255), width=max(1, round(s(4))))
    hi = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hi).ellipse([s(488 - 48), s(400 - 76), s(488 + 48), s(400 + 76)], fill=(255, 255, 255, int(0.6 * 255)))
    ball = Image.alpha_composite(ball, hi)
    bd = ImageDraw.Draw(ball)  # re-bind: alpha_composite returned a new image
    seam = (0x0C, 0x3F, 0xA5, 255)

    def cap_line(x1, y1, x2, y2, w):
        r2 = s(w) / 2
        bd.line([(s(x1), s(y1)), (s(x2), s(y2))], fill=seam, width=max(1, round(s(w))))
        for (px, py) in ((x1, y1), (x2, y2)):
            bd.ellipse([s(px) - r2, s(py) - r2, s(px) + r2, s(py) + r2], fill=seam)

    cap_line(530, 312, 530, 628, 11)
    cap_line(498, 402, 562, 402, 9)
    cap_line(498, 470, 562, 470, 9)
    cap_line(498, 538, 562, 538, 9)
    ball = ball.rotate(-22, center=(s(bx), s(by)), resample=Image.BICUBIC)

    # soft drop shadow from the ball silhouette
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sil = Image.new("RGBA", (S, S), (4, 29, 84, 255))
    shadow.paste(sil, (0, round(s(14))), ball.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(s(20)))
    shadow.putalpha(shadow.split()[3].point(lambda v: int(v * 0.45)))
    fg = Image.alpha_composite(fg, shadow)
    fg = Image.alpha_composite(fg, ball)

    # scale the composition up about the tile centre (mirrors the SVG scale(1.3)
    # group) so the ball + posts aren't lost at small home-screen sizes
    SC = 1.3
    big = fg.resize((round(S * SC), round(S * SC)), Image.BICUBIC)
    off = round((S - S * SC) / 2)  # negative: recentres the enlarged layer
    img.paste(big, (off, off), big)

    # ── rounded-tile clip (rx 230) ──
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=s(230), fill=255)
    img.putalpha(mask)
    return img


def write_icons(out_html_path: str) -> dict:
    """Emit the icon set next to the output HTML: the vector SVG (favicon/logo)
    plus PNGs iOS/Android can use, and a web-app manifest. Returns the relative
    filenames. PNGs are supersampled at 2x then downscaled for clean edges."""
    from PIL import Image

    out_dir = os.path.dirname(os.path.abspath(out_html_path))

    with open(os.path.join(out_dir, ICON_SVG), "w", encoding="utf-8") as f:
        f.write(_ICON_SVG_SRC)

    master = _render_icon(2048)  # supersample, then downscale for clean edges
    master.resize((180, 180), Image.LANCZOS).save(os.path.join(out_dir, APPLE_ICON))
    master.resize((512, 512), Image.LANCZOS).save(os.path.join(out_dir, ICON_512))

    manifest = {
        "name": "Punters Mate", "short_name": "Punters Mate",
        "display": "standalone", "background_color": "#061634", "theme_color": "#082E86",
        "icons": [
            {"src": ICON_SVG, "sizes": "any", "type": "image/svg+xml"},
            {"src": ICON_512, "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))

    return {"svg": ICON_SVG, "png180": APPLE_ICON, "png512": ICON_512, "manifest": MANIFEST}


def _view_to_records(view: pd.DataFrame) -> list[dict]:
    """Round the projection view to plain JSON-friendly records (NaN -> None).

    D_proj and D_sigma are sent so the disposal floor can be rebuilt in-browser at
    any confidence level (floor = proj - z(conf)*sigma); sigma keeps 2 dp so the
    floor is exact after the floor()/round-down."""
    cols = ["player", "GP", "R_n",
            "D_avg", "D_L5", "D_vs", "D_n", "D_proj", "D_sigma",
            "G_avg", "G_L5", "G_vs", "G_proj", "G_floor", "G_any",
            "F_avg", "F_L5", "F_vs", "F_proj", "F_floor", "F_sigma"]
    ints = {"GP", "D_n", "R_n", "G_floor"}
    round2 = {"D_sigma", "F_sigma"}
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


LINEUP_WINDOW_DAYS = 9  # only chase named teams for games kicking off this soon
ODDS_WINDOW_DAYS = 9    # only pull Sportsbet disposal odds for games this soon
ODDS_MIN_EDGE = 0.05    # surface a value pick only when the model edge clears this


def _attach_odds(records: list[dict], ladder: dict, proj_key: str, sigma_key: str,
                 ladder_key: str, best_key: str) -> int:
    """Join a game's Sportsbet N+ ladder for one stat onto its player records.

    Adds per matched player: `<ladder_key>` ({N: price}) so the page can show the
    bookie price at the dial-driven floor, and `<best_key>` (the best value lean,
    or None) computed against the model's Normal(proj, sigma) using `proj_key` /
    `sigma_key`. EV is independent of the confidence dial, so it's settled here at
    build time. Returns the count of players matched to a ladder."""
    by_csv = {csv: sb for sb, csv in
              SB.match_players(list(ladder), [r["player"] for r in records]).items()}
    matched = 0
    for r in records:
        sb = by_csv.get(r["player"])
        if not sb:
            continue
        rung = ladder[sb]
        r[ladder_key] = {str(n): p for n, p in sorted(rung.items())}
        r[best_key] = SB.best_value(rung, r.get(proj_key), r.get(sigma_key),
                                    min_edge=ODDS_MIN_EDGE)
        matched += 1
    return matched


def _attach_ladder(records: list[dict], ladder: dict, ladder_key: str) -> int:
    """Attach just the N+ price ladder (no Normal best-value) -- used for goals,
    which are modelled Poisson, so the round-email multi can price each goal leg
    at the bet's line (1+ = anytime, else the projection's whole-goal floor)."""
    by_csv = {csv: sb for sb, csv in
              SB.match_players(list(ladder), [r["player"] for r in records]).items()}
    matched = 0
    for r in records:
        sb = by_csv.get(r["player"])
        if not sb:
            continue
        r[ladder_key] = {str(n): p for n, p in sorted(ladder[sb].items())}
        matched += 1
    return matched


def build_games(df: pd.DataFrame, fixture: list[dict], year: int = M.CURRENT_SEASON,
                conf: float = M.DEFAULT_CONF, verify: bool = True, odds: bool = False):
    """For each fixture game where both clubs have current-season data, attach
    precomputed home/away projection views. Every current-season player is
    included (sorted by disposal projection); the page filters by floor in-browser
    so the floor>=10 cut tracks the confidence the user picks.

    When a game is within LINEUP_WINDOW_DAYS we pull the official named team from
    the AFL API and drop players not in the 22 (so dropped/injured/managed players
    disappear); each side is flagged `home_named`/`away_named`. If the team isn't
    named yet (or the pull fails) we keep everyone and flag the side as not named.
    Returns (games, skipped)."""
    have = set(df[df.season == year]["team"].unique())
    today = date.today()

    # Sportsbet odds (opt-in). One scraper + one events list for the whole build;
    # any network/bot-block failure degrades to "no odds" without killing the page.
    odds_scraper = sb_events = None
    if odds:
        try:
            odds_scraper = SB.make_scraper()
            sb_events = SB.list_events(odds_scraper)
            print(f"  Sportsbet: {len(sb_events)} AFL events for odds matching")
        except Exception as e:
            print(f"  Sportsbet events pull failed ({type(e).__name__}: {e}); building without odds")
            odds = False

    lineup_cache: dict = {}

    def lineups_for(rnd):
        if rnd not in lineup_cache:
            try:
                lineup_cache[rnd] = L.named_players(df, year, int(rnd), verify=verify)
            except Exception as e:  # network/parse/SSL -> degrade to "show all"
                print(f"  lineup pull failed for round {rnd}: {type(e).__name__}: {e}")
                lineup_cache[rnd] = {}
        return lineup_cache[rnd]

    games, skipped = [], []
    for g in fixture:
        home, away = g["home"], g["away"]
        if home not in have or away not in have:
            skipped.append(g)
            continue

        # Only the imminent round can have a posted lineup; skip the API for
        # far-future games (they'd all return "not named" anyway).
        within = False
        try:
            gd = datetime.strptime((g["date"] or "")[:10], "%Y-%m-%d").date()
            within = 0 <= (gd - today).days <= LINEUP_WINDOW_DAYS
        except ValueError:
            within = False
        lin = lineups_for(g["round"]) if within else {}
        home_named, away_named = lin.get(home), lin.get(away)

        vh = M.team_view(df, home, away, None, conf)
        va = M.team_view(df, away, home, None, conf)
        if home_named is not None:
            vh = vh[vh["player"].isin(home_named)]
        if away_named is not None:
            va = va[va["player"].isin(away_named)]

        home_rec = _view_to_records(vh)
        away_rec = _view_to_records(va)

        # Player-prop odds: only for imminent games (props post a day or two out)
        # and only when --odds is on. We pull two N+ ladders -- disposals and AFL
        # Fantasy points -- and value each against its own Normal(proj, sigma).
        # Per-game failures are non-fatal.
        if odds and within and sb_events is not None:
            try:
                ev = SB.find_event(home, away, g["date"], sb_events)
                if ev:
                    eid = ev["id"]
                    d_ladder = SB.stat_ladder(eid, "disposals", odds_scraper)
                    f_ladder = SB.stat_ladder(eid, "fantasy", odds_scraper)
                    g_ladder = SB.stat_ladder(eid, "goals", odds_scraper)
                    if d_ladder:
                        mh = _attach_odds(home_rec, d_ladder, "D_proj", "D_sigma",
                                          "od_ladder", "od_best")
                        ma = _attach_odds(away_rec, d_ladder, "D_proj", "D_sigma",
                                          "od_ladder", "od_best")
                        print(f"  odds: {home} v {away} -> disposals {mh}+{ma} priced")
                    else:
                        print(f"  odds: {home} v {away} -> no disposal markets yet")
                    if f_ladder:
                        fh = _attach_odds(home_rec, f_ladder, "F_proj", "F_sigma",
                                          "od_ladder_F", "od_best_F")
                        fa = _attach_odds(away_rec, f_ladder, "F_proj", "F_sigma",
                                          "od_ladder_F", "od_best_F")
                        print(f"  odds: {home} v {away} -> fantasy {fh}+{fa} priced")
                    else:
                        print(f"  odds: {home} v {away} -> no fantasy markets yet")
                    if g_ladder:
                        gh = _attach_ladder(home_rec, g_ladder, "od_ladder_G")
                        ga = _attach_ladder(away_rec, g_ladder, "od_ladder_G")
                        print(f"  odds: {home} v {away} -> goals {gh}+{ga} priced")
            except Exception as e:
                print(f"  odds pull failed for {home} v {away}: {type(e).__name__}: {e}")

        games.append({
            "round": g["round"], "date": g["date"], "unixtime": g.get("unixtime"),
            "venue": g["venue"],
            "home": home, "away": away,
            "home_named": home_named is not None,
            "away_named": away_named is not None,
            "home_view": home_rec,
            "away_view": away_rec,
        })
    return games, skipped


def _floor_tinted(proj, sigma, ladder, conf) -> bool:
    """True if a player's disposal/fantasy FLOOR cell carries betting value
    (amber or green), mirroring the page's in-browser tint: floor = proj - z*sigma,
    edge at the floor rung = P(>=floor)*price - 1 >= 0. This catches marginal amber
    picks the `od_best` lean (>=5% edge) misses -- e.g. a +2% floor cell -- so every
    tinted pick on the page gets an availability read, not just the strong leans."""
    if not ladder or not sigma or proj is None:
        return False
    z = NormalDist().inv_cdf(conf)
    floor = max(0, math.floor(proj - z * sigma))
    price = ladder.get(str(floor))
    if price is None:
        return False
    return NormalDist().cdf((proj - floor) / sigma) * price - 1 >= 0


def _is_value_pick(r: dict, conf: float) -> bool:
    """A pick worth a context read: a >=5% value lean (od_best/od_best_F) OR a
    floor cell tinted amber/green on disposals or fantasy."""
    return bool(r.get("od_best") or r.get("od_best_F")
                or _floor_tinted(r.get("D_proj"), r.get("D_sigma"), r.get("od_ladder"), conf)
                or _floor_tinted(r.get("F_proj"), r.get("F_sigma"), r.get("od_ladder_F"), conf))


def attach_sentiment(games: list[dict], conf: float = M.DEFAULT_CONF) -> int:
    """Attach recent forum/news sentiment to the VALUE players in each game.

    A "value player" is any pick the page tints: a >=5% value lean (`od_best` /
    `od_best_F`) OR a floor cell tinted amber/green at `conf` (see _is_value_pick).
    Scoping to tinted picks keeps the network cost small while covering every pick
    a punter might actually back. Each gets an `r['sentiment']` dict (see
    forum_sentiment.player_sentiment). One shared scraper + same-day disk cache for
    the whole build; any per-player failure is non-fatal. Returns the count read.

    Requires VADER (vaderSentiment); if it isn't installed we skip with a note so
    a missing optional dep never breaks the page build."""
    if FS._analyzer() is None:
        print("  sentiment: vaderSentiment not installed -- skipping (pip install vaderSentiment)")
        return 0
    scraper = FS.make_scraper()
    cache = FS._load_cache()
    today = str(date.today())
    done = 0
    for g in games:
        try:
            rnd = int(g["round"])
        except (TypeError, ValueError):
            rnd = None
        # Each side's opponent anchors the forward-looking fetch on THIS game.
        for side, opp in (("home_view", g["away"]), ("away_view", g["home"])):
            for r in g[side]:
                if not _is_value_pick(r, conf):
                    continue
                try:
                    s = FS.cached_player_sentiment(r["player"], opponent=opp,
                                                   round_no=rnd, scraper=scraper,
                                                   cache=cache, today=today)
                except Exception as e:
                    print(f"  sentiment: {r['player']} failed ({type(e).__name__}: {e})")
                    s = None
                if s:
                    r["sentiment"] = s
                    done += 1
    FS._save_cache(cache)
    print(f"  sentiment: {done} value players given a forward-looking read")
    return done


# ── HTML shell (mobile-first; data injected as JSON, rendered in JS) ────────────

_CSS = """
/* Light theme: white page, blue ink. Cards are white with a soft shadow;
   accents echo the app icon (blue disposals, gold goals). */
:root{--bg:#ffffff;--card:#ffffff;--inset:#f3f7fd;
      --line:rgba(12,47,107,.14);--ink:#0c2f6b;--mut:#5b6f96;
      --disp:#1a63dc;--goal:#bf820a;--fan:#7a3ff2;--home:#1a63dc;--away:#e0612f;
      --good:#1a9e6a;--mid:#c0890f;--brand:#1551bf;}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;color:var(--ink);background:#fff;
     font:15px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:0 12px 48px}
/* sticky picker so you can switch games while scrolling on a phone */
header.top{position:sticky;top:0;z-index:10;
           background:rgba(255,255,255,.92);
           backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
           padding:14px 0 11px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:7px;margin:0 0 11px}
.logo{width:34px;height:34px;flex:none;display:block}
/* two-tone Archivo wordmark, reused from the app-icon lockup */
.wordmark{font-family:'Archivo',system-ui,sans-serif;font-weight:900;font-size:22px;
          letter-spacing:-.6px;color:var(--ink);line-height:1;margin:0}
.wordmark span{color:var(--disp)}
select{width:100%;background:#fff;color:var(--ink);border:1px solid var(--line);
       border-radius:10px;padding:12px 12px;font-size:16px;-webkit-appearance:none;
       appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),
       linear-gradient(135deg,var(--mut) 50%,transparent 50%);
       background-position:calc(100% - 18px) 19px,calc(100% - 13px) 19px;
       background-size:5px 5px,5px 5px;background-repeat:no-repeat}
.meta{color:var(--mut);font-size:12.5px;margin:9px 2px 0}
.empty{color:var(--mut);font-size:12.5px;padding:14px;font-style:italic}
/* glossary key &mdash; lives inside the Method & caveats panel */
.legend{color:var(--mut);font-size:12px;line-height:1.5;display:flex;gap:7px 16px;
        flex-wrap:wrap;margin:8px 0 2px}
.legend b{color:var(--ink)}
.legend .vlg.clear{color:var(--good)}.legend .vlg.border{color:var(--mid)}
.games{display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
      box-shadow:0 4px 16px rgba(12,47,107,.08)}
.card h2{margin:0;padding:12px 15px;font-size:15px;border-bottom:1px solid var(--line);color:var(--ink);
         display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.card.home h2{border-left:4px solid var(--home)}
.card.away h2{border-left:4px solid var(--away)}
.card h2 small{color:var(--mut);font-weight:400;font-size:12px}
.lineup{margin-left:auto;font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
        padding:3px 7px;border-radius:99px;white-space:nowrap;align-self:center}
.lineup.named{color:#0f7a4f;background:rgba(26,158,106,.12);border:1px solid rgba(26,158,106,.35)}
.lineup.pending{color:var(--mut);background:var(--inset);border:1px solid var(--line)}
.prow{padding:12px 14px;border-bottom:1px solid var(--line)}
.prow:last-child{border-bottom:none}
.phead{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px}
.pname{font-weight:600;font-size:15px;color:var(--ink)}
.pmeta{color:var(--mut);font-size:11.5px;white-space:nowrap}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stat{background:var(--inset);border:1px solid var(--line);border-radius:11px;padding:10px 11px}
.stat .lbl{display:flex;justify-content:space-between;align-items:center;
           font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.stat .big{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.15;
           margin:3px 0 2px}
.stat.disp .big{color:var(--disp)}.stat.fan .big{color:var(--fan)}
.stat .big .u{font-size:11px;font-weight:600;color:var(--mut);margin-left:3px}
.proj{display:inline-block;font-size:11px;font-weight:600;color:var(--mut)}
.bar{height:6px;border-radius:99px;background:rgba(12,47,107,.1);overflow:hidden;margin:7px 0 6px}
.bar>span{display:block;height:100%;border-radius:99px}
.stat.disp .bar>span{background:var(--disp)}.stat.fan .bar>span{background:var(--fan)}
.stat.fan .sbline .sbtag{color:var(--fan)}.stat.fan .sbline.ev .sbtag{color:var(--good)}
.det{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}
/* Sportsbet disposal odds: price at the floor + best value lean */
.sbline{margin-top:7px;font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums;
        display:flex;justify-content:space-between;align-items:center;gap:8px}
.sbline .sbtag{font-weight:700;color:var(--disp)}
.sbline.ev,.sbline.ev .sbtag{color:var(--good)}
.sbval{margin-top:7px;font-size:11px;font-weight:700;color:var(--good);
       background:rgba(26,158,106,.1);border:1px solid rgba(26,158,106,.4);
       border-radius:9px;padding:6px 9px;display:flex;justify-content:space-between;
       align-items:center;gap:8px;font-variant-numeric:tabular-nums}
.sbnone{margin-top:7px;font-size:10.5px;color:var(--mut)}
.badge{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;
       letter-spacing:.02em}
.badge.yes{background:rgba(26,158,106,.14);color:var(--good);border:1px solid rgba(26,158,106,.4)}
.pct.hi{color:var(--good)}.pct.mid{color:var(--mid)}.pct.lo{color:var(--mut)}
.pct.elite{color:var(--good);font-weight:800}
/* Goals: a compact, full-width probability strip under the disposals/fantasy pair
   (sparse Poisson, so it's framed by scoring % rather than a Normal floor) */
.gstrip{grid-column:1/-1;display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px;
        padding:7px 11px;border:1px solid var(--line);border-radius:11px;
        background:transparent;font-variant-numeric:tabular-nums}
.gstrip .glabel{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);font-weight:600}
.gstrip .gprob{font-size:13px;color:var(--mut)}
.gstrip .gprob b{font-size:15px;color:var(--goal);font-weight:700}
.gstrip .gprob.sub b,.gstrip .gprob.sub{color:var(--mut)}
.gstrip.hot .gprob b{color:var(--good)}
.gstrip .gdet{font-size:10.5px;color:var(--mut);margin-left:auto}
/* priced cells (disposals, fantasy) tinted by betting value at the floor: clear (green) / borderline (amber) */
.stat.val-clear{border-color:rgba(26,158,106,.5);background:rgba(26,158,106,.1)}
.stat.val-border{border-color:rgba(192,137,15,.5);background:rgba(192,137,15,.13)}
/* heads-up banner: greens are the model's biggest edge but historically the least reliable */
.headsup{background:var(--inset);border:1px solid var(--line);border-left:4px solid var(--mid);
         border-radius:12px;padding:12px 15px;margin:0 0 18px;font-size:12.7px;line-height:1.55;color:var(--ink)}
.headsup .h{display:block;font-weight:800;margin-bottom:3px;letter-spacing:.01em}
.headsup .g{color:var(--good);font-weight:700}
.headsup .a{color:var(--mid);font-weight:700}
.headsup .tip{display:block;margin-top:7px;padding-top:7px;border-top:1px solid var(--line);color:var(--mut)}
.headsup .tip b{color:var(--ink)}
.na{color:var(--mut)}
/* Forum/news sentiment strip on a value player: tone chip + availability warning
   + a few linked headlines. Context only — never a probability input. */
.senti{margin-top:11px;border-top:1px dashed var(--line);padding-top:9px;font-size:11.5px}
.senti-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.senti-tone{font-weight:700;font-size:9.5px;text-transform:uppercase;letter-spacing:.05em;
            padding:2px 8px;border-radius:99px}
.senti-tone.bull{color:var(--good);background:rgba(26,158,106,.12);border:1px solid rgba(26,158,106,.4)}
.senti-tone.bear{color:var(--away);background:rgba(224,97,47,.12);border:1px solid rgba(224,97,47,.4)}
.senti-tone.neu{color:var(--mut);background:var(--inset);border:1px solid var(--line)}
.senti-warn{font-weight:700;color:var(--away);background:rgba(224,97,47,.12);
            border:1px solid rgba(224,97,47,.45);border-radius:99px;padding:2px 8px;font-size:9.5px;
            text-transform:uppercase;letter-spacing:.04em}
.senti-meta{color:var(--mut);font-variant-numeric:tabular-nums}
.senti-items{list-style:none;margin:8px 0 0;padding:0}
.senti-items li{margin:5px 0;line-height:1.4;color:var(--mut)}
.senti-items a{color:var(--ink);text-decoration:none}
.senti-items a:hover{text-decoration:underline;color:var(--disp)}
.senti-src{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;
           color:var(--mut);margin-right:6px}
.senti-item.risk .senti-src{color:var(--away)}
.senti-vs{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;
          color:var(--disp);background:rgba(26,99,220,.1);border-radius:99px;
          padding:1px 5px;margin-right:6px}
.senti-when{color:var(--mut);font-size:10px;margin-left:6px;font-variant-numeric:tabular-nums}
/* collapsible reference panels (betting strategy + method): one shared type
   scale — 12.5px/1.55 body, 13px heads, 20px list indent, 6px between items */
.strategy{background:var(--inset);border:1px solid var(--line);border-radius:16px;margin-top:16px}
.stratbody li{margin:6px 0}
.stratbody b{color:var(--ink)}
.chip{display:inline-block;padding:1px 6px;border-radius:99px;font-size:10.5px;
      background:#fff;border:1px solid var(--line)}
.strategy>summary{cursor:pointer;padding:16px 17px;font-size:13px;font-weight:700;color:var(--ink);
       list-style:none;display:flex;justify-content:space-between;align-items:center}
.strategy>summary::-webkit-details-marker{display:none}
.strategy>summary::after{content:'\\002b';color:var(--mut);font-weight:700;font-size:16px}
.strategy[open]>summary::after{content:'\\2212'}
.strategy>summary:hover{color:var(--disp)}
.stratbody{padding:0 17px 16px;color:var(--mut);font-size:12.5px;line-height:1.55}
.stratbody ul{margin:8px 0 0;padding-left:20px}
.stratbody ol{margin:10px 0 14px;padding-left:20px}
.stratbody p.rules{margin:14px 0 8px;color:var(--ink);font-weight:600}
table.be{width:100%;border-collapse:collapse;margin:10px 0 14px;font-variant-numeric:tabular-nums}
table.be th,table.be td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);font-size:12.5px}
table.be th{color:var(--mut);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}
table.be td:first-child,table.be th:first-child{text-align:left}
table.be tr:last-child td{border-bottom:none}
table.be td.be-ok{color:var(--good)}
.caveat{font-size:12.5px;line-height:1.55;margin:10px 0 0;color:var(--mut)}
.stratbody>.caveat:first-child{margin-top:0}
@media(min-width:780px){
  .wrap{padding:0 20px 60px}
  .logo{width:38px;height:38px}
  .wordmark{font-size:25px}
  .games{grid-template-columns:1fr 1fr;align-items:start}
}
@media(max-width:340px){.stats{grid-template-columns:1fr}}
"""

_JS = """
const DATA = __DATA__;
const GCONF = Math.round(DATA.goal_conf * 100);   // goals confidence (server-side)
// One-sided normal quantile for the disposal floor: floor = proj - z(conf)*sigma.
const Z = {90:1.2816, 85:1.0364, 80:0.8416, 75:0.6745};
const FLOOR_MIN = 10;          // only show players whose disposal floor clears this
const sel = document.getElementById('game');
const out = document.getElementById('out');
const meta = document.getElementById('meta');
const curConf = Math.round(DATA.conf * 100);   // disposal-floor confidence (fixed)
const ZCONF = Z[curConf] || Z[85];
const VAL_CLEAR = 0.05;        // model edge over the bookie price that counts as "clear" value
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
// Render a game's kick-off in AWST (UTC+8, no daylight saving), e.g.
// "Thu 4 Jun, 5:30pm AWST". Prefer the UTC epoch; fall back to the raw string.
const _DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const _MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fmtDate(g){
  let Y, Mo, Da, Dow, H, Mi, hasTime = false;
  if (g && g.unixtime){
    // shift the UTC instant by +8h, then read the UTC fields = AWST wall clock
    const d = new Date((g.unixtime + 8 * 3600) * 1000);
    Y = d.getUTCFullYear(); Mo = d.getUTCMonth(); Da = d.getUTCDate();
    Dow = d.getUTCDay(); H = d.getUTCHours(); Mi = d.getUTCMinutes(); hasTime = true;
  } else {
    const m = String((g && g.date) || '').match(/(\\d{4})-(\\d{2})-(\\d{2})(?:[ T](\\d{2}):(\\d{2}))?/);
    if(!m) return (g && g.date) || '';
    const d = new Date(+m[1], +m[2]-1, +m[3]);
    Y = +m[1]; Mo = +m[2]-1; Da = +m[3]; Dow = d.getDay();
    H = +(m[4]||0); Mi = +(m[5]||0); hasTime = (m[4] !== undefined);
  }
  let out = _DOW[Dow] + ' ' + Da + ' ' + _MON[Mo];
  if (hasTime){
    let h = H; const ap = h < 12 ? 'am' : 'pm'; h = h % 12 || 12;
    out += ', ' + h + ':' + String(Mi).padStart(2,'0') + ap + (g && g.unixtime ? ' AWST' : '');
  }
  return out;
}
function f1(v){ return v === null ? DASH : v.toFixed(1); }
function f0(v){ return v === null ? DASH : Math.round(v).toString(); }
function pctCls(p){ return p > HOT ? 'elite' : (p >= GCONF ? 'hi' : (p >= 50 ? 'mid' : 'lo')); }
// Escape forum/news text before injecting it (titles are third-party strings).
function esc(s){ return (s||'').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
// Forum/news sentiment strip for a value player: a tone chip, an availability
// warning when injury/selection words appear, then a few linked headlines. This
// is qualitative context for a pick the model already flagged -- never a number
// that feeds the floor or the edge.
function sentiHtml(r){
  const s = r.sentiment;
  if (!s) return '';
  const tone = s.label === 'bullish' ? 'bull' : (s.label === 'bearish' ? 'bear' : 'neu');
  const srcBits = Object.keys(s.by_source).map(k => s.by_source[k] + ' ' + k).join(DOT);
  let head = '<div class="senti-head">'+
    '<span class="senti-tone ' + tone + '">' + s.label + '</span>'+
    (s.availability ? '<span class="senti-warn">\\u26a0 availability</span>' : '')+
    '<span class="senti-meta">' + s.n + ' mention' + (s.n === 1 ? '' : 's') +
    DOT + srcBits + '</span></div>';
  let items = '<ul class="senti-items">';
  s.items.forEach(it => {
    items += '<li class="senti-item' + (it.risk ? ' risk' : '') + '">'+
      '<span class="senti-src">' + it.source + '</span>'+
      (it.opp ? '<span class="senti-vs">vs</span>' : '')+
      '<a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + '</a>'+
      (it.when ? '<span class="senti-when">' + esc(it.when) + '</span>' : '') + '</li>';
  });
  items += '</ul>';
  return '<div class="senti">' + head + items + '</div>';
}

// Standard normal CDF (Abramowitz & Stegun 7.1.26) so the page can put the
// model's probability on the Sportsbet price at whatever floor the dial picks.
function normCdf(z){
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989422804014327 * Math.exp(-z * z / 2);
  const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 +
            t * (-1.821255978 + t * 1.330274429))));
  return z > 0 ? 1 - p : p;
}
// Disposal floor at the fixed confidence: proj - z*sigma, rounded down, never
// below 0. <3 recent games (sigma null) -> flat 15% haircut.
function dispFloor(r){
  if (r.D_proj === null || r.D_proj === undefined) return null;
  if (r.D_sigma === null) return Math.max(0, Math.floor(r.D_proj * 0.85));
  return Math.max(0, Math.floor(r.D_proj - ZCONF * r.D_sigma));
}
// Fantasy floor: same Normal model as disposals on the AFL Fantasy projection.
function fanFloor(r){
  if (r.F_proj === null || r.F_proj === undefined) return null;
  if (r.F_sigma === null) return Math.max(0, Math.floor(r.F_proj * 0.85));
  return Math.max(0, Math.floor(r.F_proj - ZCONF * r.F_sigma));
}

function dispStat(r, o3, dmax){
  const floor = dispFloor(r);
  // Sportsbet block + value tint: price the displayed floor against the model and
  // tint the cell green (clear value) / amber (borderline) / none. The floor sits
  // at ~conf% by construction, so it's always inside a backable probability band.
  let valCls = '', odds = '';
  if (r.od_ladder){
    const price = r.od_ladder[String(floor)];
    if (price !== undefined && r.D_sigma){
      const mp = normCdf((r.D_proj - floor) / r.D_sigma);
      const ev = mp * price - 1;
      valCls = ev >= VAL_CLEAR ? ' val-clear' : (ev >= 0 ? ' val-border' : '');
      odds += '<div class="sbline' + (ev > 0 ? ' ev' : '') + '">'+
        '<span class="sbtag">SB ' + floor + '+ $' + price.toFixed(2) + '</span>'+
        '<span>model ' + Math.round(mp * 100) + '% ' + DOT + 'mkt ' + Math.round(100 / price) + '%' +
        DOT + (ev >= 0 ? '+' : '') + Math.round(ev * 100) + '%</span></div>';
    } else if (price === undefined){
      odds += '<div class="sbnone">no Sportsbet line at ' + floor + '+ disposals</div>';
    }
    // a different rung that prices up as clearer value than the floor itself
    if (r.od_best && r.od_best.n !== floor){
      const b = r.od_best;
      odds += '<div class="sbval"><span>\\u25b2 better: back ' + b.n + '+ @ $' + b.price.toFixed(2) +
        '</span><span>+' + Math.round(b.edge * 100) + '% edge</span></div>';
    }
  }
  const w = (r.D_proj && dmax) ? Math.max(4, Math.min(100, r.D_proj / dmax * 100)) : 0;
  const det = 'proj ' + f1(r.D_proj) + DOT + 'avg ' + f1(r.D_avg) + DOT +
              'L5 ' + f1(r.D_L5) + DOT + 'v' + o3 + ' ' + f1(r.D_vs) + ' (' + r.D_n + ')';
  return '<div class="stat disp' + valCls + '"><div class="lbl"><span>Disposals</span></div>'+
    '<div class="big">' + f0(floor) + '<span class="u">min</span></div>'+
    '<div class="bar"><span style="width:' + w.toFixed(0) + '%"></span></div>'+
    '<div class="det">' + det + '</div>' + odds + '</div>';
}
// Goals is a sparse Poisson count, not a Normal floor, so it gets a compact strip
// framed by scoring probability (the real anytime/2+ markets) rather than a "min"
// floor. P(>=1) = 1 - e^-lambda, P(>=2) = 1 - e^-lambda(1+lambda), lambda = proj.
function goalStrip(r, o3){
  const lam = r.G_proj;
  const has = lam !== null && lam !== undefined;
  const p1 = has ? Math.round((1 - Math.exp(-lam)) * 100) : null;
  const p2 = has ? Math.round((1 - Math.exp(-lam) * (1 + lam)) * 100) : null;
  const backed = p1 !== null && p1 >= GCONF;     // model backs an anytime goal
  const any = r.G_any;                           // supporting: empirical 1+ rate
  const anyTxt = any === null ? DASH : Math.round(any) + '%';
  const det = 'proj ' + f1(r.G_proj) + DOT + anyTxt + ' 1+ rate' + DOT +
              'avg ' + f1(r.G_avg) + DOT + 'L5 ' + f1(r.G_L5) + DOT + 'v' + o3 + ' ' + f1(r.G_vs);
  return '<div class="gstrip' + (backed ? ' hot' : '') + '">'+
    '<span class="glabel">Goals</span>'+
    '<span class="gprob"><b>' + (p1 === null ? DASH : p1 + '%') + '</b> anytime</span>'+
    '<span class="gprob sub">' + (p2 === null ? DASH : p2 + '%') + ' 2+</span>'+
    '<span class="gdet">' + det + '</span></div>';
}
// Best-edge Fantasy rung AT OR BELOW the model floor. Sportsbet posts Fantasy in
// steps of 5, so the exact integer floor is rarely on the board -- we suggest the
// nearest priced rung the model still clears at >= the floor's confidence. We never
// suggest a rung above the floor: that would be a line our own model rates below
// its confidence bar (improbable), contradicting the "back the floor" premise.
// Constrained this way, the max-edge rung is the highest safe rung (best odds that
// still clears conf%).
function bestFanRung(r, floor){
  if (!r.od_ladder_F || !r.F_sigma || floor === null) return null;
  let best = null;
  for (const k in r.od_ladder_F){
    const n = +k, price = r.od_ladder_F[k];
    if (n > floor) continue;                 // only rungs at/below the floor (model_p >= conf)
    const mp = normCdf((r.F_proj - n) / r.F_sigma);
    const ev = mp * price - 1;
    if (!best || ev > best.ev) best = {n, price, mp, ev};
  }
  return best;
}
function fanStat(r, o3, fmax){
  const floor = fanFloor(r);
  // Value the best in-band rung (the coarse ladder rarely prices the exact floor)
  // and tint the cell green (clear) / amber (borderline) / none, like disposals.
  let valCls = '', odds = '';
  if (r.od_ladder_F){
    const b = bestFanRung(r, floor);
    if (b){
      valCls = b.ev >= VAL_CLEAR ? ' val-clear' : (b.ev >= 0 ? ' val-border' : '');
      odds += '<div class="sbline' + (b.ev > 0 ? ' ev' : '') + '">'+
        '<span class="sbtag">SB ' + b.n + '+ $' + b.price.toFixed(2) + '</span>'+
        '<span>model ' + Math.round(b.mp * 100) + '% ' + DOT + 'mkt ' + Math.round(100 / b.price) + '%' +
        DOT + (b.ev >= 0 ? '+' : '') + Math.round(b.ev * 100) + '%</span></div>';
    } else {
      odds += '<div class="sbnone">no Sportsbet fantasy line at or below the floor</div>';
    }
  }
  const w = (r.F_proj && fmax) ? Math.max(4, Math.min(100, r.F_proj / fmax * 100)) : 0;
  const det = 'proj ' + f1(r.F_proj) + DOT + 'avg ' + f1(r.F_avg) + DOT +
              'L5 ' + f1(r.F_L5) + DOT + 'v' + o3 + ' ' + f1(r.F_vs) + ' (' + r.D_n + ')';
  return '<div class="stat fan' + valCls + '"><div class="lbl"><span>Fantasy</span></div>'+
    '<div class="big">' + f0(floor) + '<span class="u">min pts</span></div>'+
    '<div class="bar"><span style="width:' + w.toFixed(0) + '%"></span></div>'+
    '<div class="det">' + det + '</div>' + odds + '</div>';
}
function teamCard(side, team, opp, view, named){
  const o3 = opp.slice(0, 3);
  // Lineup badge: green when the official team is named (list filtered to the
  // playing squad), muted when not yet named (showing all current-season players).
  const tag = named
    ? '<span class="lineup named">named team</span>'
    : '<span class="lineup pending">team not yet named &middot; all players</span>';
  const head = '<h2>' + team + ' <small>vs ' + opp + '</small>' + tag + '</h2>';
  // Filter to players whose disposal floor clears FLOOR_MIN at the chosen
  // confidence; the cut moves with the toggle (looser conf -> higher floors).
  const shown = view.filter(r => { const f = dispFloor(r); return f !== null && f >= FLOOR_MIN; });
  if (!shown.length)
    return '<div class="card ' + side + '">' + head +
      '<div class="empty">No players clear a ' + FLOOR_MIN + '-disposal floor at ' + curConf + '% confidence.</div></div>';
  const dmax = Math.max(...shown.map(r => r.D_proj || 0), 1);
  const fmax = Math.max(...shown.map(r => r.F_proj || 0), 1);
  let rows = '';
  shown.forEach((r) => {
    rows += '<div class="prow"><div class="phead">'+
      '<div class="pname">' + r.player + '</div>'+
      '<div class="pmeta">' + r.GP + ' GP \\u00b7 ' + r.R_n + 'g</div></div>'+
      '<div class="stats">' + dispStat(r, o3, dmax) + fanStat(r, o3, fmax) +
      goalStrip(r, o3) + '</div>' + sentiHtml(r) + '</div>';
  });
  return '<div class="card ' + side + '">' + head + rows + '</div>';
}
function render(i){
  curGame = i;
  const g = DATA.games[i];
  meta.textContent = 'Round ' + g.round + DOT + fmtDate(g) + DOT + (g.venue || '');
  out.innerHTML =
    teamCard('home', g.home, g.away, g.home_view, g.home_named) +
    teamCard('away', g.away, g.home, g.away_view, g.away_named);
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
renderStrategy(curConf);
// Default to the next game that hasn't started yet (fall back to the first).
const now = new Date();
let start = DATA.games.findIndex(g => g.date && new Date(g.date.replace(' ', 'T')) >= now);
if (start < 0) start = 0;
if (DATA.games.length) { sel.value = start; render(start); }
"""


# Inline icon mark for the header lockup (football sailing through the goal posts).
# Inverted for the site lockup: blue line-art on a transparent/white ground (no
# square app-tile), so it sits cleanly next to the wordmark. Kept inline so the
# mark + wordmark render as one unit without a second request.
_HEADER_MARK = (
    '<svg class="logo" viewBox="236 265 552 552" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="Punters Mate">'
    '<defs>'
    '<linearGradient id="pmBall" x1="0" y1="0" x2="0.4" y2="1">'
    '<stop offset="0%" stop-color="#3D8BFF"/><stop offset="100%" stop-color="#1A63DC"/></linearGradient>'
    '</defs>'
    # behind posts (fainter blue) then goal posts (solid blue)
    '<line x1="328" y1="430" x2="328" y2="760" stroke="#1A63DC" stroke-width="24" stroke-linecap="round" opacity="0.30"/>'
    '<line x1="696" y1="430" x2="696" y2="760" stroke="#1A63DC" stroke-width="24" stroke-linecap="round" opacity="0.30"/>'
    '<line x1="426" y1="300" x2="426" y2="760" stroke="#1A63DC" stroke-width="30" stroke-linecap="round" opacity="0.85"/>'
    '<line x1="598" y1="300" x2="598" y2="760" stroke="#1A63DC" stroke-width="30" stroke-linecap="round" opacity="0.85"/>'
    # ball flight path
    '<path d="M376 788 Q472 612 530 532" fill="none" stroke="#1A63DC" stroke-width="18" '
    'stroke-linecap="round" stroke-dasharray="2 58" opacity="0.55"/>'
    # the ball: solid blue with white seam + cross-laces
    '<g transform="rotate(22 530 470)">'
    '<ellipse cx="530" cy="470" rx="130" ry="186" fill="url(#pmBall)"/>'
    '<line x1="530" y1="306" x2="530" y2="634" stroke="#fff" stroke-width="13" stroke-linecap="round"/>'
    '<line x1="496" y1="400" x2="564" y2="400" stroke="#fff" stroke-width="10" stroke-linecap="round"/>'
    '<line x1="496" y1="470" x2="564" y2="470" stroke="#fff" stroke-width="10" stroke-linecap="round"/>'
    '<line x1="496" y1="540" x2="564" y2="540" stroke="#fff" stroke-width="10" stroke-linecap="round"/>'
    '</g></svg>'
)


def to_html(games, skipped, path, csv, conf=M.DEFAULT_CONF, goal_conf=M.GOAL_CONF):
    cpc = round(conf * 100)
    gpc = round(goal_conf * 100)
    data = {"generated": str(date.today()), "season": M.CURRENT_SEASON,
            "conf": conf, "goal_conf": goal_conf, "games": games}
    payload = json.dumps(data, separators=(",", ":"))
    js = _JS.replace("__DATA__", payload)
    icons = write_icons(path)

    has_odds = any("od_ladder" in r for g in games
                   for r in g["home_view"] + g["away_view"])
    has_senti = any("sentiment" in r for g in games
                    for r in g["home_view"] + g["away_view"])

    # When odds are present, explain the green/amber tint that replaced the old dial.
    value_legend = (
        '<span><b class="vlg clear">green</b> / <b class="vlg border">amber</b> disposal or fantasy '
        'cell &mdash; clear / borderline betting value vs the Sportsbet price</span>'
    ) if has_odds else ''
    senti_legend = (
        '<span><b>buzz</b> on a value player &mdash; <b>forward-looking</b> chatter about <i>this</i> '
        'game (previews, selection, role/fitness), not last-round recaps. Shows tone '
        '(<b style="color:var(--good)">bullish</b>/<b style="color:var(--away)">bearish</b>), an '
        '<b style="color:var(--away)">&#9888; availability</b> flag on injury/selection words, and a '
        '<b>vs</b> marker on items naming the opponent. Context, not a number in the model.</span>'
    ) if has_senti else ''
    legend_items = (
        f'<span><b>min</b> disposal floor &mdash; projection minus the {cpc}% margin of safety</span>'
        f'<span><b>min pts</b> AFL Fantasy floor &mdash; same {cpc}% margin of safety</span>'
        '<span><b>anytime</b> model P(1+ goal); <b>2+</b> P(2+) &mdash; Poisson(proj)</span>'
        '<span><b>1+ rate</b> supporting: share of recent games with a goal</span>'
        '<span><b>proj</b> blended projection</span>'
        f'{value_legend}'
        f'{senti_legend}'
    )

    # Folded-in betting insight from the singles-vs-multi break-even analysis.
    strategy = (
        '<details class="strategy"><summary>Betting strategy &mdash; singles vs multis</summary>'
        '<div class="stratbody">'
        '<div class="caveat">A floor is "<b>clears at <span class="beConf">85</span>%</b>", not '
        '"wins your bet". It only pays if the bookie line sits <b>at or below</b> the floor, and '
        'legs in a same-game multi are <b>correlated</b> &mdash; that correlation only ever helps '
        'the book. Treat each leg as roughly a <span class="beConf">85</span>% shot and price '
        'accordingly.</div>'
        '<p class="rules">For the best outcome over time:</p>'
        '<ol>'
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
        '</div></details>'
    )

    odds_note = ""
    if has_odds:
        odds_note = (
            '<li><b>Sportsbet odds</b> &mdash; for imminent games we pull Sportsbet\'s '
            '<span class="chip">N+ disposals</span> and <span class="chip">N+ fantasy points</span> '
            'ladders. <b>SB N+ $price</b> is the price at '
            'the floor; <b>model%</b> is our Normal(proj,&sigma;) chance of clearing it, '
            '<b>mkt%</b> the bookie\'s implied (1/price), and the last figure is the edge '
            '(model &times; price &minus; 1). The disposal/fantasy cell is tinted '
            '<span style="color:var(--good);font-weight:700">green</span> when that edge is '
            '&ge;5% (clear value), <span style="color:var(--mid);font-weight:700">amber</span> '
            'when it is 0&ndash;5% (borderline), and left plain otherwise. A '
            '<span style="color:var(--good);font-weight:700">&#9650; better</span> line flags a '
            'different rung that prices up as stronger value than the floor. Implied% ignores the '
            'bookie\'s margin, so treat small edges with care. Sportsbet posts <b>fantasy in steps '
            'of 5</b>, so we suggest the nearest priced rung <b>at or below the floor</b> (never '
            'above it &mdash; that would be a line the model already rates below its confidence); '
            'if no rung sits at/below the floor, no fantasy line is shown.</li>')
    skip_note = ""
    if skipped:
        names = ", ".join(sorted({t for g in skipped for t in (g["home"], g["away"])}))
        skip_note = (f'<li><b>{len(skipped)}</b> fixtured game(s) hidden &mdash; no '
                     f'current-season data for: {names}.</li>')
    notes = (
        '<details class="strategy"><summary>Method &amp; caveats</summary>'
        '<div class="stratbody"><ul>'
        f'<li><b>Disposal floor</b> &mdash; the projection minus a margin of safety '
        '(z<sub>conf</sub> &times; the player\'s recent std-dev), so erratic players are '
        f'discounted more. Under a normal approximation they clear it in about {cpc}% of '
        'games.</li>'
        '<li><b>Goals</b> &mdash; goals are a sparse count, so instead of a floor the compact '
        'strip shows scoring <b>probability</b> under Poisson(&lambda;=projection): '
        '<b>anytime</b> = P(&ge;1 goal) = 1&minus;e<sup>&minus;&lambda;</sup>, <b>2+</b> = P(&ge;2). '
        f'The anytime figure turns green when it clears {gpc}%. <b>1+ rate</b> is a supporting '
        'figure &mdash; the separate empirical share of recent games with a goal.</li>'
        f'<li><b>Fantasy floor</b> &mdash; AFL Fantasy (Classic) points, derived from the box '
        'score (<span class="chip">3&middot;K + 2&middot;HB + 3&middot;M + 4&middot;T + '
        '1&middot;HO + 6&middot;G + 1&middot;B + FF &minus; 3&middot;FA</span>). It is a '
        'high-count, roughly symmetric stat, so it uses the same Normal floor as disposals '
        f'(proj minus the {cpc}% margin of safety), calibrated to within ~1% in backtest.</li>'
        '<li><b>Projection</b> blend (backtest-tuned, season-anchored) &mdash; recent form '
        'is split across three windows (L3/L5/L10). With H2H: '
        '<span class="chip">0.65&middot;season + 0.15&middot;L3 + 0.05&middot;L5 + 0.05&middot;L10 + 0.10&middot;H2H</span>, '
        'without: <span class="chip">0.55&middot;season + 0.15&middot;L3 + 0.05&middot;L5 + 0.25&middot;L10</span>; '
        'H2H is recency-weighted (2026 counts 3&times; a 2024 meeting).</li>'
        f'<li>Players are sorted by disposal projection and '
        f'<b>filtered to a disposal floor of at least 10</b> at {cpc}% confidence. '
        'Floors use current-season games (recent games across seasons if too few).</li>'
        '<li><b>Named teams</b> &mdash; once the official team is posted (usually Thursday '
        'night), the list is cut to the named 22 (emergencies excluded) and the card shows '
        '<span class="lineup named">named team</span>. Until then it shows '
        '<span class="lineup pending">team not yet named</span> and lists every current-season '
        'player. Source: the AFL API.</li>'
        f'{odds_note}'
        f'{skip_note}'
        '</ul>'
        '<p class="rules">Key</p>'
        f'<div class="legend">{legend_items}</div>'
        '<div class="caveat">Confidence floors &middot; disposals '
        f'<span id="subDisp">{cpc}</span>% &middot; goals {gpc}% &middot; {M.CURRENT_SEASON} '
        f'&middot; generated {date.today()} &middot; source: {csv}</div>'
        '</div></details>'
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>PuntersMate</title>
<link rel="icon" type="image/svg+xml" href="{icons['svg']}">
<link rel="apple-touch-icon" sizes="180x180" href="{icons['png180']}">
<link rel="manifest" href="{icons['manifest']}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;900&display=swap" rel="stylesheet">
<meta name="theme-color" content="#ffffff">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Punters Mate">
<style>{_CSS}</style></head>
<body><div class="wrap">
<header class="top"><div class="brand">{_HEADER_MARK}<h1 class="wordmark">Punters<span>Mate</span></h1></div>
<select id="game" aria-label="Select match"></select>
<p class="meta" id="meta"></p></header>
<div class="headsup">
<span class="h">&#9888; Don&rsquo;t bet the <span class="g">greens</span> only</span>
A <span class="g">green</span> cell is where our model sees the most value &mdash; but that&rsquo;s
also where the market is most likely to know something we don&rsquo;t. It&rsquo;s not bad luck:
a big &ldquo;edge&rdquo; usually means we&rsquo;re missing late info. In our weekly tracking so far the
<span class="g">green</span> picks have cleared their floor the <b>least</b> often &mdash; around
two-thirds of the time, versus roughly nine in ten for <span class="a">amber</span>.
<span class="tip"><b>Simple fix:</b> favour <span class="a">amber</span> over <span class="g">green</span>.
&nbsp;<b>Best results so far:</b> <span class="a">amber</span> + un-highlighted picks &mdash; the most
reliable, though at shorter odds (lower returns). Biggest edge &ne; safest bet.</span>
</div>
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
    ap.add_argument("--odds", action="store_true",
                    help="pull Sportsbet odds, flag value, and attach forum/news sentiment "
                         "to each value pick (AU IP only; off by default)")
    ap.add_argument("--no-sentiment", action="store_true",
                    help="skip the forum/news sentiment pass on a --odds build (faster; no network for chatter)")
    # Deprecated: sentiment now runs with --odds by default. Kept so old commands
    # (and the documented --sentiment) still work -- it just ensures --odds is on.
    ap.add_argument("--sentiment", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # Value players are identified by the odds pass, so sentiment needs odds on.
    if args.sentiment and not args.odds:
        print("--sentiment enables --odds (value players come from the odds pass)")
        args.odds = True

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

    games, skipped = build_games(df, fixture, args.year, args.conf,
                                 verify=not args.insecure, odds=args.odds)
    # Sentiment runs on every odds build (value picks come from the odds pass);
    # --no-sentiment opts out for a faster, network-light build.
    if args.odds and not args.no_sentiment:
        attach_sentiment(games, args.conf)
    to_html(games, skipped, args.out, args.csv, args.conf)


if __name__ == "__main__":
    main()
