# AFL 2026 Player Stats — Data Sources

Quick reference for available AFL data sources.

## 1. AFL Tables — `afltables.com`

| Property | Detail |
|---|---|
| Cost | Free |
| Auth | None |
| Player stats depth | 1965 → present |
| Update cadence | Within 24 h of each match |
| Cloudflare bypass | Required (`cloudscraper`) |

**Season index URL**
```
https://afltables.com/afl/stats/{year}.html
```
**Player profile URL**
```
https://afltables.com/afl/stats/players/{Initial}/{Last_First}.html
```

Stat columns: kicks, handballs, marks, disposals, goals, behinds, hit_outs,
tackles, rebound_50s, inside_50s, clearances, contested_possessions,
uncontested_possessions, contested_marks, marks_inside_50, free_kicks_for,
free_kicks_against, brownlow_votes, one_percenters, bounces, goal_assist,
time_on_ground_pct, supercoach, afl_fantasy.

---

## 2. Squiggle API — `api.squiggle.com.au`

| Property | Detail |
|---|---|
| Cost | Free |
| Auth | None |
| Player stats | **None** — game scores + tips only |

Useful for fixture data, live scores, 50+ community model predictions.

---

## 3. API-Sports AFL API — `v1.afl.api-sports.io`

| Property | Detail |
|---|---|
| Cost | Free tier: 100 req/day |
| Auth | `x-apisports-key` header |

Per-game player stats via `/games/statistics/players?id={game_id}`.

---

## Recommendation

**AFL Tables** (primary) — free, comprehensive, updated within 24 h of each match.
**Squiggle** — zero-setup fixture and score feed.
**API-Sports** — structured JSON if you prefer an API over scraping.
