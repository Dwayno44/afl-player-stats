# PuntersMate — Session Handoff (2026-06-05): forward-looking forum/news sentiment

**Repo:** `C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats` (GitHub `Dwayno44/afl-player-stats`, live `https://dwayno44.github.io/afl-player-stats/`).
**Read first:** the project's own `HANDOVER.md` (source of truth for the base app, data sources, gotchas) and the prior `C:\Users\megan\AppData\Local\Temp\punters-mate-handoff.md` (the pre-pivot state). This doc only covers **the new sentiment feature** built this session — don't duplicate the rest.

Build with venv + `--odds` (AU IP required); add `--sentiment` for the new layer:
`.venv/Scripts/python.exe matchup_app.py --odds --sentiment --out matchups.html`

---

## What this session built (NOT yet committed)

A **forward-looking forum/news sentiment layer** on the "value" players (those the odds pass flags with `od_best`/`od_best_F`). It answers *"what's being said about THIS week's game"* — previews, team selection, role/tagging, fitness/availability — and deliberately **excludes last-round recaps** (the stats already carry recent form; this was the user's explicit steer).

### New/changed files (uncommitted working tree)
- **`forum_sentiment.py`** (NEW) — the whole feature. Keyless, no API keys (project rule).
- **`matchup_app.py`** (M) — `import forum_sentiment as FS`; new `attach_sentiment(games)` (after `build_games`); new `--sentiment` flag (implies `--odds`, since value players come from the odds pass); call after `build_games` in `main()`; JS `esc()` + `sentiHtml()` render fns; `sentiHtml(r)` wired into the `teamCard` player-row; `.senti*` CSS block; `senti_legend` + `has_senti` in `to_html`.
- **`requirements.txt`** (M) — added `vaderSentiment>=3.3` (installed in the venv already).
- **`.gitignore`** (M) — added `.sentiment_cache.json`.
- **`.claude/launch.json`** (M, gitignored) — added a `punters-mate-root` http.server config on :8138 (serves repo root; note `preview_start` started the existing `punters-mate-docs` :8137 config instead — workaround used: copy build into `docs/` then `rm` it).

> The other untracked files (`hitouts_value.py`, `icon-512.png`, `punters-mate-icon.svg`, `site.webmanifest`) are **pre-existing**, not from this session — leave them.

### How it works (read `forum_sentiment.py` for detail — well-commented)
- **3 keyless sources:** Reddit r/AFL via the Atom `search.rss` feed (the `.json` endpoint hard-403s now — important), Google News RSS search (`when:{N}d`, AU locale), best-effort BigFooty XenForo `/forum/search/search` scrape (full-text, keeps the result *snippet* + the prefix label chips like "Preview"/"Changes" which are forward signals; degrades to `[]` silently).
- **Offline sentiment:** VADER (`vaderSentiment`) + a hand-written `FOOTY_LEXICON` (managed/soreness/omitted = bearish; cleared/named/in-form = bullish). No model server / no key — that's why VADER over an LLM.
- **Fixture-anchored + forward gate** (`is_forward`): each player's fetch is paired with **this round's opponent** (`CLUB_ALIASES` for 18 clubs) and round number. An item is kept only if it names the opponent, OR carries a selection/role marker (`FWD_MARKER`), OR is an availability/injury/tag item (`RISK_WORDS`) — AND is not explicitly about another round (`_round_nums`) or a finished-result recap (`BACK_MARKER`).
- **Per-source relevance** (`_relevant`): Reddit requires the surname in the **title** (thread title = topic; this killed the recurring "Dylan Stephens" false positive); News/BigFooty allow title-or-body.
- **Availability flag** (`RISK_WORDS`) surfaces as a ⚠ badge; injuries are treated as forward-looking.
- **Same-day disk cache** `.sentiment_cache.json` (gitignored), keyed `norm(name)|norm(opponent)`. Delete it to force a fresh pull.
- CLI: `python forum_sentiment.py player "Isaac Heeney" --opp "St Kilda" --round 13 [--no-cache]`; also `reddit|news|bigfooty "<name>"` raw dumps.

### Verified working (DOM-checked via `preview_eval`, not screenshots — the 1.3 MB page times screenshots out)
Last `--odds --sentiment` build → **3 forward-looking reads** (down from 16 backward-heavy in the first cut):
- **Jake Bowey (v Coll) — BEARISH ⚠ availability** — "Injury Report | Latest on Fritsch, Bowey and more" (the actionable one).
- **Zak Butters (v WC) — BULLISH** — "Midfield bulls Reid, Butters set to collide in blockbuster".
- **Hayden McLean (v StK) — NEUTRAL** — "…Now the Swans have a selection headache".
Panel renders: tone chip (bullish/bearish/neutral), ⚠ availability, optional `vs` marker on opponent-naming items, linked dated headlines with source tags.

---

## Key decisions made (so you don't relitigate)
- User chose: sources = Reddit + Google News + BigFooty; scope = **value players only**; direction = **rebuild forward-only now** (drop backward momentum); strictness = **broad** (opponent OR selection terms, manage stale-preview leakage via round-number filter).
- Sentiment is framed as **context, not a model input** — never feeds the floor/edge. Keep the responsible-gambling framing; read & analyse only (never place/cash out — standing project rule).

## Known limitations / honest caveats
- **Forward content is genuinely thin early-week.** Most players (even in-form ones) correctly show **no panel** until ~Thu–Sat when teams are named & previews drop. That's by design, and lines up with the existing named-team/odds window. Rebuilding closer to the weekend will populate it.
- VADER scores headline *tone*, which can misread match-report verbs ("run riot" reads negative). The forward gate removes most of this, but it's why the score is "context" not signal.
- Team-level previews (e.g. "Sydney vs St Kilda Tips") name the *teams*, not the player, so `_relevant` drops them from a player's panel by design (avoids cloning one generic preview onto every player).

## Open threads / the user's next-step question (unanswered)
The user ran `/handoff` right after I asked which of these to do — pick up here:
1. **Commit** this work (see conventions below), and/or
2. **Publish to `docs/index.html`** (currently the build only went to gitignored `matchups.html`; `docs/index.html` is untouched), and/or
3. **Rebuild closer to the weekend** to see the panel fill out once teams are named.
Possible follow-on tuning if asked: weight news over forum chatter; down-weight match-report verbs; surface a per-*game* preview (team-level) separate from per-player.

## Standing constraints (unchanged — do not violate)
- Per-commit identity `-c user.name="Dwayne Smith" -c user.email="<redacted>"`; trailer `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` (the repo's existing trailer convention — confirm the model string the user wants). Never touch global git config. **Commit only when asked.** New commits, not amends.
- No third-party API keys anywhere; no `--insecure`/`verify=False`. Odds + sentiment builds need an AU IP; CI (US runner) builds without odds — **do not** make CI rebuild odds/sentiment.
- If publishing: deploy is GitHub Pages from `main` `/docs`. The weekly publish workflow only `git add`s a few files — confirm `docs/index.html` gets staged.

## Suggested skills for the next session
- **`code-review`** — before committing; `matchup_app.py` + new `forum_sentiment.py` have accumulated. Good fit given the new module.
- **`verify`** / **`run`** — to confirm a fresh `--odds --sentiment` build renders (use `preview_eval` DOM checks, **not** screenshots; serve via `.claude/launch.json` `punters-mate-docs` on :8137, navigate to the built file).
- **`update-config`** — only if the user wants an automated/scheduled rebuild (e.g. a Thu/Fri build to catch named teams).
