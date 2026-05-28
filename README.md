# AFL Player Stats

Scrapes 2026 AFL player statistics from [afltables.com](https://afltables.com) via a GitHub Actions workflow.

## Usage

### GitHub Actions (no local setup needed)

Go to **Actions → Fetch AFL Player Stats → Run workflow**, pick a season and optional round, click **Run**.

The workflow saves two CSV artifacts (30-day retention):
- `stats_2026.csv` — every player, season totals
- `bontempelli_2026_games.csv` — sample player game-by-game log

### Local

```bash
pip install -r requirements.txt

python3 afltables.py season 2026 --out stats_2026.csv
python3 afltables.py player "Marcus Bontempelli" --season 2026 --games
python3 afltables.py team Collingwood --season 2026
python3 afltables.py players 2026
```

### Run tests

```bash
python3 test_parser.py   # 16 tests, no network required
```

## Stat fields

`kicks` · `handballs` · `disposals` · `marks` · `goals` · `behinds` · `hit_outs` · `tackles` · `rebound_50s` · `inside_50s` · `clearances` · `contested_possessions` · `uncontested_possessions` · `free_kicks_for` · `free_kicks_against` · `contested_marks` · `marks_inside_50` · `brownlow_votes` · `one_percenters` · `goal_assist` · `time_on_ground_pct` · `supercoach` · `afl_fantasy`

## Notes

- AFL Tables uses Cloudflare — the scraper uses `cloudscraper` to bypass it.
- GitHub Actions runners are not blocked by Cloudflare, making this the simplest way to fetch live data without local setup.
- See [SOURCES.md](SOURCES.md) for a full comparison of available AFL data sources.
