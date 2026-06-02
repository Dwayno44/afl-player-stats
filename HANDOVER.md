# Punters Mate — Handover

Snapshot for picking the project up on a **personal machine** (off the Fortescue
corporate network). Written 2026-06-02.

---

## 1. What this is

**Punters Mate** — an AFL footy-betting helper for backing player **disposals**
and **goals**. It builds a single static page (`docs/index.html`) that, per
fixtured match, lists each named player with a **disposal floor** and a **goal
floor** at a chosen confidence, plus a betting-strategy panel (singles vs multis,
break-even odds). All the maths runs client-side so the confidence "dial" updates
the page live.

- **Live site:** GitHub Pages from `main` → `/docs`
  → https://dwayno44.github.io/afl-player-stats/
- **Repo:** https://github.com/Dwayno44/afl-player-stats.git (branch `main`)

---

## 2. New-machine setup

```bash
git clone https://github.com/Dwayno44/afl-player-stats.git
cd afl-player-stats
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
python test_parser.py            # 16 tests, no network — sanity check
```

- **Python:** CI uses 3.11; this was developed on 3.14. Anything ≥3.11 is fine.
- **`requirements.txt`** now includes `numpy` and `pillow` (pillow is needed by the
  icon renderer in `matchup_app.py` — see §7 note).
- **No `--insecure` on your personal machine.** That flag (and `verify=False` in
  the code) only existed to get through Fortescue's SSL-intercepting proxy. On a
  home network, drop it — TLS verifies normally.

### Build the page locally

```bash
python matchup_app.py --out docs/index.html
```

Fixture is pulled live from Squiggle; stats come from the committed CSV. Open
`docs/index.html` in a browser (or serve the folder) to view.

---

## 3. Where we left off (all committed & pushed)

Recent commits on `main`:

| Commit | What |
|--------|------|
| `afe1da7` | Scale up the icon's ball + posts (1.3× about centre) so it reads at home-screen size |
| `1aa71ec` | Mad-cunt confidence **dial** is now a real slider (green→amber→red risk track) |
| `ed82c6e` | Punters Mate icon set + page reskin (blue-mesh glass look) |
| `0f39cb7` | Filter to officially **named teams** via the AFL API |
| `30a718d` | Confidence dial, floor≥10 filter, betting-strategy panel |

The icon redesign, page reskin, slider dial, and icon-scaling work the user asked
for this session are **all done, verified in preview, committed and pushed.**

**Uncommitted right now** (part of this handover): `requirements.txt` (added
numpy/pillow) and this `HANDOVER.md`. Commit them on the new machine if not already.

---

## 4. THE NEXT TASK — player disposal odds (this is why we're moving machines)

**Goal:** pull live AFL player **disposal** odds (Sportsbet) so we can compare a
bookie's over/under line against our computed disposal floor and flag +EV bets.

**Why it stalled on the work machine:** Fortescue's **Netskope** proxy blocks
`api.the-odds-api.com` under category *"Prohibited Sites, Gambling"* — the request
returns a 403 block page and never reaches the API. Nothing to do with the key or
endpoint; it's a network policy. **It must run off the corporate network.** That's
the whole reason for the move.

### The Odds API specifics (validated against their v4 docs, not yet run live)

- **Base:** `https://api.the-odds-api.com/v4`
- **Sport key:** `aussierules_afl`
- **API key (free tier, ~500 req/month):** `09f3f2c77702fe876bc6ea6cb33fb7b7`
  - ⚠️ This key is exposed in this repo/handover and in work-machine shell history.
    **Rotate it** at the-odds-api.com when you get on the new machine, and keep the
    new one out of git (env var or untracked file — see below).
- **Flow:**
  1. `GET /v4/sports/aussierules_afl/events?apiKey=…`
     → list events, grab an `id`. *(free — no quota cost)*
  2. `GET /v4/sports/aussierules_afl/events/{eventId}/odds`
     with params: `apiKey`, `regions=au`, `markets=player_disposals`,
     `bookmakers=sportsbet`, `oddsFormat=decimal`.
- **Market keys to try:** `player_disposals`, and the alternate-lines variant
  `player_disposals_alternate`. (Other AFL props exist: `player_goals`,
  `player_marks`, `player_tackles`, etc.)
- **Response shape:** `bookmakers[] → markets[] → outcomes[]`, where each outcome
  has `description` (player name), `name` ("Over"/"Under"), `point` (the line),
  `price` (decimal odds).
- **Quota headers** on each response: `x-requests-remaining`, `x-requests-used`.
  Watch these — the per-event odds call costs 1 (or more) per market×region.
- **Timing:** player props usually only populate a day or two before each game.
  Empty markets ≠ broken — just no lines posted yet.

### Suggested first step on the new machine

Write a standalone `odds.py` (kept out of the CI build) that:
1. reads the key from `ODDS_API_KEY` env var (not hard-coded),
2. lists AFL events, takes `--event <id>` or defaults to the soonest,
3. pulls `player_disposals` (+ `_alternate`) from Sportsbet in decimal,
4. prints each player's line + over/under prices, and the quota used.

Add `odds.py` secrets handling to `.gitignore` if you cache responses. Don't commit
the key.

### Then: the actual value — match odds to our floors

Our page already computes a **disposal floor** = "clears at *conf*% of the time"
(`floor = projection − z(conf)·σ`, see `matchup.py` / `matchup_app.py`). The bet is
+EV when a bookie's **Over** line sits **at or below** our floor at fair-or-better
odds. The break-even maths is already in the page's strategy panel
(fair per-leg odds = 1/conf). So the integration is: join Odds-API player lines to
our per-player floors (same name-normalisation approach as `lineups.py` uses for the
AFL API → CSV join) and highlight where `bookie_line ≤ floor` and `price ≥ 1/conf`.

---

## 5. File map

| File | Role |
|------|------|
| `matchup_app.py` | **Main renderer.** Builds `docs/index.html`: embeds data as JSON, ships the CSS/JS, renders the icon set (`write_icons`), the confidence dial, strategy panel. Entry point `main()`. |
| `matchup.py` | Stats engine: per-team player view, projections (season + L3/L5/L10 + H2H blend), disposal σ, goal floor (Poisson). |
| `lineups.py` | Pulls the officially **named 22** from the AFL API (token → compseason → matches → roster) and joins to CSV names. Degrades gracefully if not yet named. |
| `fixtures.py` | Fixture/venue pull from the Squiggle API. |
| `afltables.py` | Scraper for afltables.com player stats (uses `cloudscraper` for Cloudflare). CLI: `season`, `player`, `team`, `players`. |
| `update_stats.py` | Incremental stats refresh (current season's new round) → updates the CSV. `--full` re-scrapes everything. |
| `backtest.py` | Backtest harness used to tune the projection blend. |
| `venues.py` | Venue metadata. |
| `test_parser.py` | 16 offline parser tests. |
| `games_2022_2026.csv` | The committed stats dataset (2022–2026, player format `"Surname, Given"`). |
| `fixture_2026.json` | Cached fixture (optional `--fixture` input). |
| `docs/` | The published site: `index.html` + icon assets (`punters-mate-icon.svg`, `apple-touch-icon.png`, `icon-512.png`, `site.webmanifest`). |
| `.github/workflows/publish-matchups.yml` | Weekly auto-rebuild + commit of the page (Tue 20:00 UTC). |
| `.github/workflows/afl-stats.yml` | Manual stats-fetch workflow (CSV artifacts). |

---

## 6. Data sources (all live, no auth except where noted)

- **Player stats:** afltables.com via `cloudscraper` (Cloudflare-protected). GitHub
  runners aren't Cloudflare-blocked, which is why CI is the easy path for refreshes.
- **Fixtures/venues:** Squiggle API.
- **Lineups:** official AFL API (Champion Data backed). Token via
  `POST api.afl.com.au/cfs/afl/WMCTok`, passed as `x-media-mis-token` header.
  2026 men's compSeason id = 85.
- **Odds (NEW, pending):** The Odds API — see §4.

---

## 7. Gotchas & known issues

- **Pillow/numpy in `requirements.txt`:** just added. The icon renderer
  (`write_icons` / `_render_icon` in `matchup_app.py`) needs both. Without Pillow the
  CI page build crashes. If you ever see `ModuleNotFoundError: PIL`, that's this.
- **Icon assets in the publish workflow:** `publish-matchups.yml` only `git add`s
  `games_2022_2026.csv docs/index.html docs/apple-touch-icon.png`. The other
  regenerated icon files (`icon-512.png`, `punters-mate-icon.svg`,
  `site.webmanifest`) aren't staged by CI. Fine as long as the icon source doesn't
  change in an auto-run — but if you tweak the icon, commit those manually (as we
  did) or widen the `git add` list.
- **CRLF warning on commit** (Windows): harmless — git normalising line endings.
- **The "mad cunt" dial:** 4 steps map to disposal confidence `[90, 85, 80, 75]`
  (`CONF_STEPS` in the page JS). Goals stay fixed at 65% regardless of the dial.
- **Corporate-net flags:** any `--insecure` / `verify=False` you see is only for the
  Fortescue proxy. Not needed (and less safe) on a personal machine.

---

## 8. Conventions

- Commit trailer used this project: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
- New commits, not amends. Deploy is GitHub Pages from `main` `/docs`.
- Keep the API key (and any future secrets) out of git.

---

## 9. First moves on the new machine (checklist)

- [ ] Clone repo, set up venv, `pip install -r requirements.txt`, run `test_parser.py`.
- [ ] `python matchup_app.py --out docs/index.html` (no `--insecure`) — confirm it builds and looks right in a browser.
- [ ] **Rotate** the Odds API key; put the new one in an `ODDS_API_KEY` env var.
- [ ] Live-test The Odds API (now unblocked): list AFL events → pull `player_disposals` for one event from Sportsbet. Confirm market exists and inspect the shape.
- [ ] Write `odds.py` per §4; then wire odds-vs-floor comparison into the page.
- [ ] Commit `requirements.txt` + `HANDOVER.md` if they weren't already.
