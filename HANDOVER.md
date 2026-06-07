# Punters Mate — Handover

Snapshot for picking the project up on a **personal machine** (off the Fortescue
corporate network). Written 2026-06-02.

---

## 1. What this is

**Punters Mate** — an AFL footy-betting helper for backing player **disposals**
and **goals**. It builds a single static page (`docs/index.html`) that, per
fixtured match, lists each named player with a **disposal floor** and a **goal
floor** at a fixed confidence, plus a betting-strategy panel (singles vs multis,
break-even odds). For imminent games it pulls the Sportsbet "N+ disposals" ladder
and tints each disposal cell green/amber by how much betting value it carries
against the bookie price. All the maths runs client-side.

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

## 4. Player disposal odds — DONE (via Sportsbet direct, no API key)

**Goal (achieved):** compare a bookie's disposal milestones against our computed
disposal floor and flag value bets on the page.

**How it works now.** `sportsbet_odds.py` pulls Sportsbet's Same Game Multi
**"N+ Disposals" ladder** straight from their internal JSON API via `cloudscraper`
(same Akamai/Cloudflare trick as `afltables.py`). **No key, no quota, no account** —
the ladder prices every integer milestone (10+, 11+, … 40+) per player, which is
exactly what our floor model wants. Endpoint:
`GET https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports/Events/{eventId}`
→ `marketList[]`; the disposal markets are the ones named `"<N>+ Disposals"`, each
with `selections[]` of `{name: player, price: {winPrice: decimal}}`.

**The value calc.** Each disposal milestone *N* has an implied prob `1/winPrice`;
our model gives `P(disposals ≥ N)` from `Normal(D_proj, D_sigma)`; edge =
`model_P × price − 1`. The page tints a player's disposal cell **green** when the
edge at their floor is ≥5%, **amber** at 0–5%, and leaves it plain otherwise. Name
joins reuse `lineups.py`'s normaliser (Sportsbet "Given Surname" → CSV
"Surname, Given"; club names via `SB2CSV`).

**Opt-in & geo-locked.** Sportsbet geo-restricts to AU, so the odds path is opt-in
(`matchup_app.py --odds`) and the weekly CI rebuild (US runner) just builds the page
without odds — the default build is unaffected.

> **The Odds API was abandoned.** The earlier plan used the-odds-api.com, but for
> AFL it only exposes two discrete disposal points per player (no milestone ladder),
> so it can't drive this feature. That dependency, its `odds.py` helper, and its API
> key have all been removed. No third-party key is used anywhere in the project.

---

## 5. File map

| File | Role |
|------|------|
| `matchup_app.py` | **Main renderer.** Builds `docs/index.html`: embeds data as JSON, ships the CSS/JS, renders the icon set (`write_icons`), the value-tinted player cards, strategy panel. `--odds` attaches Sportsbet odds. Entry point `main()`. |
| `sportsbet_odds.py` | Fetches the Sportsbet "N+ disposals" ladder (cloudscraper, no key), name-joins to CSV players, computes per-rung value vs the model. CLI: `events`, `ladder`. |
| `matchup.py` | Stats engine: per-team player view, projections (season + L3/L5/L10 + H2H blend), disposal σ, goal floor (Poisson). |
| `lineups.py` | Pulls the officially **named 22** from the AFL API (token → compseason → matches → roster) and joins to CSV names. Degrades gracefully if not yet named. |
| `fixtures.py` | Fixture/venue pull from the Squiggle API. |
| `afltables.py` | Scraper for afltables.com player stats (uses `cloudscraper` for Cloudflare). CLI: `season`, `player`, `team`, `players`. |
| `update_stats.py` | Incremental stats refresh (current season's new round) → updates the CSV. `--full` re-scrapes everything. |
| `backtest.py` | Backtest harness used to tune the projection blend. |
| `MODEL.md` | **Model development & backtesting record** — architecture, methodology, and every feature experiment to date (Tier-A + the CBA/minutes spike). Read for "what's been tried and what moved MAE". |
| `exp_*.py`, `probe_cba.py`, `fetch_cba.py` | Experiment scaffolding behind `MODEL.md` (TOG, concession, absence, game-script, CBA oracle). Not part of the build; `matchup.py` is unchanged by them. |
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
- **Odds:** Sportsbet internal JSON API via `cloudscraper` — no key, no quota, AU IP
  only. See §4.

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
- **Confidence is fixed** at `DEFAULT_CONF` (85%) for disposals, 65% for goals — the
  old "mad cunt" slider was removed in favour of green/amber value tinting on each
  disposal cell. The page reads the level from the embedded `DATA.conf`.
- **Corporate-net flags:** any `--insecure` / `verify=False` you see is only for the
  Fortescue proxy. Not needed (and less safe) on a personal machine.

---

## 8. Conventions

- Commit trailer used this project: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
- New commits, not amends. Deploy is GitHub Pages from `main` `/docs`.
- No third-party API keys are used. Keep any future secrets out of git (env var or
  untracked file), never hard-coded or in this doc.

---

## 9. First moves on the new machine (checklist)

- [ ] Clone repo, set up venv, `pip install -r requirements.txt`, run `test_parser.py`.
- [ ] `python matchup_app.py --out docs/index.html` (no `--insecure`) — confirm it builds and looks right in a browser.
- [ ] For value flags, build with odds (AU IP only): `python matchup_app.py --odds --out docs/index.html`. Spot-check `sportsbet_odds.py events` if no markets attach.
- [ ] Commit any uncommitted `requirements.txt` / `HANDOVER.md`.
