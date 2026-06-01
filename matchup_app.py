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
from datetime import date, datetime

import pandas as pd

import matchup as M
import fixtures as F
import lineups as L

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


LINEUP_WINDOW_DAYS = 9  # only chase named teams for games kicking off this soon


def build_games(df: pd.DataFrame, fixture: list[dict], year: int = M.CURRENT_SEASON,
                conf: float = M.DEFAULT_CONF, verify: bool = True):
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

        games.append({
            "round": g["round"], "date": g["date"], "venue": g["venue"],
            "home": home, "away": away,
            "home_named": home_named is not None,
            "away_named": away_named is not None,
            "home_view": _view_to_records(vh),
            "away_view": _view_to_records(va),
        })
    return games, skipped


# ── HTML shell (mobile-first; data injected as JSON, rendered in JS) ────────────

_CSS = """
/* Brand palette echoes the app icon: analogous blues, white ball, gold goal.
   Cards are translucent "glass" floating over a fixed blue mesh gradient. */
:root{--bg:#071a40;--card:rgba(16,44,102,.55);--inset:rgba(6,18,46,.55);
      --line:rgba(255,255,255,.12);--ink:#eef3ff;--mut:#9fb2dd;
      --disp:#4f9bff;--goal:#ffb23e;--home:#4f9bff;--away:#ff7a59;
      --good:#46d39a;--mid:#e8b54a;--brand:#3D8BFF;}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;color:var(--ink);background:#050f2b;
     background-image:radial-gradient(130% 95% at 25% -8%,#2f74ef 0%,#1551bf 28%,#0c357f 50%,#071f49 74%,#040d28 100%);
     background-attachment:fixed;
     font:15px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:0 12px 48px}
/* sticky picker so you can switch games while scrolling on a phone */
header.top{position:sticky;top:0;z-index:10;
           background:linear-gradient(180deg,rgba(5,16,43,.92),rgba(5,16,43,.72));
           backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
           padding:12px 0 10px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;margin:0 0 9px}
.logo{width:32px;height:32px;border-radius:9px;flex:none;
      box-shadow:0 3px 10px rgba(4,18,60,.5)}
h1{font-size:17px;margin:0;letter-spacing:.01em;font-weight:700}
select{width:100%;background:rgba(8,24,58,.72);color:var(--ink);border:1px solid var(--line);
       border-radius:10px;padding:12px 12px;font-size:16px;-webkit-appearance:none;
       appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),
       linear-gradient(135deg,var(--mut) 50%,transparent 50%);
       background-position:calc(100% - 18px) 19px,calc(100% - 13px) 19px;
       background-size:5px 5px,5px 5px;background-repeat:no-repeat}
.meta{color:var(--mut);font-size:12.5px;margin:9px 2px 0}
.dial{margin-top:12px}
.dial label{display:block;font-size:11px;letter-spacing:.04em;text-transform:uppercase;
            color:var(--mut);margin:0 2px 10px}
/* the dial itself: a slider knob riding a green->amber->red risk track */
#madcunt{-webkit-appearance:none;appearance:none;width:100%;height:26px;
         background:transparent;cursor:pointer;margin:0}
#madcunt::-webkit-slider-runnable-track{height:8px;border-radius:999px;
  background:linear-gradient(90deg,var(--good),var(--goal) 55%,var(--away))}
#madcunt::-moz-range-track{height:8px;border-radius:999px;
  background:linear-gradient(90deg,var(--good),var(--goal) 55%,var(--away))}
#madcunt::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:24px;height:24px;
  margin-top:-10px;border-radius:50%;border:2px solid #fff;
  background:radial-gradient(circle at 35% 30%,#fff,#cdd8f0);
  box-shadow:0 3px 10px rgba(4,18,60,.6)}
#madcunt::-moz-range-thumb{width:24px;height:24px;border-radius:50%;border:2px solid #fff;
  background:radial-gradient(circle at 35% 30%,#fff,#cdd8f0);
  box-shadow:0 3px 10px rgba(4,18,60,.6)}
#madcunt:focus-visible{outline:none}
#madcunt:focus-visible::-webkit-slider-thumb{box-shadow:0 0 0 4px rgba(61,139,255,.45)}
.dial-ticks{display:flex;justify-content:space-between;gap:4px;margin:9px 1px 0}
.dial-ticks span{flex:1;text-align:center;font-size:10.5px;line-height:1.25;color:var(--mut);
  transition:color .15s ease}
.dial-ticks span:first-child{text-align:left}
.dial-ticks span:last-child{text-align:right}
.dial-ticks span.on{color:var(--ink);font-weight:700}
.sub{color:var(--mut);font-size:12px;margin:10px 2px 14px}
.empty{color:var(--mut);font-size:12.5px;padding:14px;font-style:italic}
.legend{color:var(--mut);font-size:11.5px;display:flex;gap:6px 14px;flex-wrap:wrap;margin:12px 2px 16px}
.legend b{color:var(--ink)}
.games{display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
      backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
      box-shadow:0 8px 26px rgba(3,14,44,.35)}
.card h2{margin:0;padding:12px 15px;font-size:15px;border-bottom:1px solid var(--line);
         display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.card.home h2{border-left:4px solid var(--home)}
.card.away h2{border-left:4px solid var(--away)}
.card h2 small{color:var(--mut);font-weight:400;font-size:12px}
.lineup{margin-left:auto;font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
        padding:3px 7px;border-radius:99px;white-space:nowrap;align-self:center}
.lineup.named{color:#7ee2a8;background:rgba(63,185,80,.13);border:1px solid rgba(63,185,80,.35)}
.lineup.pending{color:var(--mut);background:var(--inset);border:1px solid var(--line)}
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
.bar{height:6px;border-radius:99px;background:rgba(255,255,255,.13);overflow:hidden;margin:7px 0 6px}
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
.na{color:#6b7aa6}
.notes{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:15px 17px;
       color:var(--mut);font-size:12px;margin-top:16px;
       backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.notes h3{color:var(--ink);margin:0 0 8px;font-size:13px}
.notes ul{margin:0;padding-left:18px}.notes li{margin:4px 0}
.chip{display:inline-block;padding:1px 6px;border-radius:99px;font-size:10.5px;
      background:var(--inset);border:1px solid var(--line)}
/* betting-strategy panel (collapsible) */
.strategy{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-top:16px;
       backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
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
.caveat{font-size:11px;line-height:1.5;margin:8px 0 0;color:#8092bd}
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
const CONF_STEPS = [90, 85, 80, 75];   // dial index -> disposal confidence
const DIAL_LABELS = ['Barely a mad cunt', 'A bit of a mad cunt',
                     'A proper mad cunt', 'A real loose cunt'];
const dialTicks = document.querySelectorAll('.dial-ticks span');
let curConf = CONF_STEPS[parseInt(madcunt.value, 10)] || 85;   // disposal confidence (live)
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
  const shown = view.filter(r => { const f = dispFloor(r, curConf); return f !== null && f >= FLOOR_MIN; });
  if (!shown.length)
    return '<div class="card ' + side + '">' + head +
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
  return '<div class="card ' + side + '">' + head + rows + '</div>';
}
function render(i){
  curGame = i;
  const g = DATA.games[i];
  meta.textContent = 'Round ' + g.round + DOT + (g.date || '') + DOT + (g.venue || '');
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
function setDial(i){
  curConf = CONF_STEPS[i];
  madcunt.setAttribute('aria-valuetext', DIAL_LABELS[i]);
  dialTicks.forEach((s, idx) => s.classList.toggle('on', idx === i));
  renderStrategy(curConf);
  if (DATA.games.length) render(curGame);
}
madcunt.addEventListener('input', e => setDial(parseInt(e.target.value, 10)));

setDial(parseInt(madcunt.value, 10));
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
    icons = write_icons(path)

    # "How much of a mad cunt do you want to be?" dial -- a real slider knob that
    # toggles disposal confidence. Steps map to 90/85/80/75 (see CONF_STEPS in JS).
    dial = (
        '<div class="dial"><label id="madcunt-label" for="madcunt">'
        'how much of a mad cunt do you want to be?</label>'
        '<input type="range" id="madcunt" min="0" max="3" step="1" value="1" '
        'aria-labelledby="madcunt-label" aria-valuetext="A bit of a mad cunt">'
        '<div class="dial-ticks">'
        '<span>Barely a mad cunt</span>'
        '<span>A bit of a mad cunt</span>'
        '<span>A proper mad cunt</span>'
        '<span>A real loose cunt</span>'
        '</div></div>'
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
        '<li>Players are sorted by disposal projection and '
        '<b>filtered to a disposal floor of at least 10</b> at the chosen confidence. '
        'Floors use current-season games (recent games across seasons if too few).</li>'
        '<li><b>Named teams</b> &mdash; once the official team is posted (usually Thursday '
        'night), the list is cut to the named 22 (emergencies excluded) and the card shows '
        '<span class="lineup named">named team</span>. Until then it shows '
        '<span class="lineup pending">team not yet named</span> and lists every current-season '
        'player. Source: the AFL API.</li>'
        f'{skip_note}'
        '</ul></div>'
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Punters Mate {M.CURRENT_SEASON}</title>
<link rel="icon" type="image/svg+xml" href="{icons['svg']}">
<link rel="apple-touch-icon" sizes="180x180" href="{icons['png180']}">
<link rel="manifest" href="{icons['manifest']}">
<meta name="theme-color" content="#082E86">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Punters Mate">
<style>{_CSS}</style></head>
<body><div class="wrap">
<header class="top"><div class="brand"><img class="logo" src="{icons['svg']}" alt=""><h1>Punters Mate</h1></div>
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

    games, skipped = build_games(df, fixture, args.year, args.conf, verify=not args.insecure)
    to_html(games, skipped, args.out, args.csv, args.conf)


if __name__ == "__main__":
    main()
