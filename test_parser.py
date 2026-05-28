"""
Parser unit tests for afltables.py
Runs against mock HTML that mirrors AFL Tables' actual page structure.
No network access required.
"""

import io
import sys
import unittest
import pandas as pd
from bs4 import BeautifulSoup

MOCK_SEASON_HTML = """
<html><body>
<table class="sortable">
  <thead>
    <tr>
      <th>#</th><th>Player</th><th>Team</th>
      <th>GM</th><th>GL</th><th>BH</th><th>KI</th><th>HB</th>
      <th>DI</th><th>MK</th><th>TK</th><th>HO</th><th>BR</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td>
      <td><a href="players/B/Bontempelli_Marcus.html">Marcus Bontempelli</a></td>
      <td>Western Bulldogs</td>
      <td>10</td><td>5</td><td>3</td><td>18</td><td>10</td>
      <td>28</td><td>6</td><td>7</td><td>0</td><td>2</td>
    </tr>
    <tr>
      <td>2</td>
      <td><a href="players/D/Dangerfield_Patrick.html">Patrick Dangerfield</a></td>
      <td>Geelong</td>
      <td>10</td><td>3</td><td>2</td><td>14</td><td>8</td>
      <td>22</td><td>5</td><td>6</td><td>0</td><td>1</td>
    </tr>
    <tr>
      <td>3</td>
      <td><a href="players/P/Pendlebury_Scott.html">Scott Pendlebury</a></td>
      <td>Collingwood</td>
      <td>10</td><td>1</td><td>0</td><td>16</td><td>12</td>
      <td>28</td><td>4</td><td>5</td><td>0</td><td>0</td>
    </tr>
  </tbody>
  <tfoot>
    <tr><td colspan="13">League totals</td></tr>
  </tfoot>
</table>
</body></html>
"""

MOCK_PLAYER_HTML = """
<html><body>
<h1>Marcus Bontempelli</h1>
<b>Born:</b> 24-Nov-1995 (30 years)<br/>
<b>Position:</b> Midfielder<br/>
<b>Debut:</b> 2014<br/>
<b>Height:</b> 193 cm<br/>
<b>Weight:</b> 93 kg<br/>
<table class="sortable">
  <caption>Career Statistics (Totals)</caption>
  <thead><tr>
    <th>Yr</th><th>Team</th><th>#</th><th>GM</th>
    <th>GL</th><th>BH</th><th>KI</th><th>HB</th><th>DI</th>
    <th>MK</th><th>TK</th><th>HO</th><th>BR</th>
  </tr></thead>
  <tbody>
    <tr><td>2024</td><td>Western Bulldogs</td><td>4</td><td>24</td>
        <td>15</td><td>8</td><td>380</td><td>210</td><td>590</td>
        <td>98</td><td>124</td><td>2</td><td>20</td></tr>
    <tr><td>2026</td><td>Western Bulldogs</td><td>4</td><td>10</td>
        <td>5</td><td>3</td><td>182</td><td>96</td><td>278</td>
        <td>55</td><td>68</td><td>0</td><td>2</td></tr>
  </tbody>
  <tfoot>
    <tr><td colspan="3">Totals</td>
        <td>242</td><td>172</td><td>84</td><td>4103</td><td>2056</td>
        <td>6159</td><td>983</td><td>1089</td><td>58</td><td>163</td></tr>
    <tr><td colspan="3">Averages</td>
        <td>-</td><td>0.71</td><td>0.35</td><td>16.95</td><td>8.50</td>
        <td>25.45</td><td>4.06</td><td>4.50</td><td>0.24</td><td>0.67</td></tr>
  </tfoot>
</table>
<table class="sortable">
  <caption>Career Statistics (Averages per game)</caption>
  <thead><tr>
    <th>Yr</th><th>Team</th><th>#</th><th>GM</th>
    <th>GL</th><th>BH</th><th>KI</th><th>HB</th><th>DI</th>
    <th>MK</th><th>TK</th><th>HO</th><th>BR</th>
  </tr></thead>
  <tbody>
    <tr><td>2024</td><td>Western Bulldogs</td><td>4</td><td>24</td>
        <td>0.63</td><td>0.33</td><td>15.83</td><td>8.75</td><td>24.58</td>
        <td>4.08</td><td>5.17</td><td>0.08</td><td>0.83</td></tr>
    <tr><td>2026</td><td>Western Bulldogs</td><td>4</td><td>10</td>
        <td>0.50</td><td>0.30</td><td>18.20</td><td>9.60</td><td>27.80</td>
        <td>5.50</td><td>6.80</td><td>0.00</td><td>0.20</td></tr>
  </tbody>
</table>
<table>
  <caption>Western Bulldogs - 2026</caption>
  <thead><tr>
    <th>Opponent</th><th>Rnd</th><th>Result</th><th>#</th>
    <th>GL</th><th>BH</th><th>KI</th><th>HB</th><th>DI</th>
    <th>MK</th><th>TK</th><th>HO</th><th>BR</th>
  </tr></thead>
  <tbody>
    <tr><td>GWS Giants</td><td>1</td><td>W 88-61</td><td>4</td>
        <td>1</td><td>0</td><td>19</td><td>10</td><td>29</td>
        <td>6</td><td>7</td><td>0</td><td>0</td></tr>
    <tr><td>Carlton</td><td>2</td><td>L 72-81</td><td>4</td>
        <td>0</td><td>1</td><td>17</td><td>9</td><td>26</td>
        <td>5</td><td>8</td><td>0</td><td>0</td></tr>
    <tr><td>Brisbane Lions</td><td>3</td><td>W 95-74</td><td>4</td>
        <td>2</td><td>0</td><td>20</td><td>11</td><td>31</td>
        <td>7</td><td>6</td><td>0</td><td>1</td></tr>
    <tr><td>Collingwood</td><td>4</td><td>W 83-70</td><td>4</td>
        <td>0</td><td>1</td><td>18</td><td>10</td><td>28</td>
        <td>5</td><td>7</td><td>0</td><td>0</td></tr>
    <tr><td>Essendon</td><td>5</td><td>L 65-78</td><td>4</td>
        <td>1</td><td>1</td><td>16</td><td>8</td><td>24</td>
        <td>4</td><td>8</td><td>0</td><td>0</td></tr>
    <tr><td>Hawthorn</td><td>6</td><td>W 101-88</td><td>4</td>
        <td>1</td><td>0</td><td>21</td><td>12</td><td>33</td>
        <td>8</td><td>5</td><td>0</td><td>1</td></tr>
    <tr><td>St Kilda</td><td>7</td><td>W 92-77</td><td>4</td>
        <td>0</td><td>0</td><td>19</td><td>10</td><td>29</td>
        <td>6</td><td>9</td><td>0</td><td>0</td></tr>
    <tr><td>Melbourne</td><td>8</td><td>L 71-84</td><td>4</td>
        <td>0</td><td>0</td><td>16</td><td>9</td><td>25</td>
        <td>4</td><td>7</td><td>0</td><td>0</td></tr>
    <tr><td>Port Adelaide</td><td>9</td><td>W 88-62</td><td>4</td>
        <td>0</td><td>0</td><td>18</td><td>10</td><td>28</td>
        <td>6</td><td>7</td><td>0</td><td>0</td></tr>
    <tr><td>Adelaide</td><td>10</td><td>W 79-68</td><td>4</td>
        <td>0</td><td>0</td><td>18</td><td>7</td><td>25</td>
        <td>4</td><td>4</td><td>0</td><td>0</td></tr>
  </tbody>
  <tfoot>
    <tr><td colspan="3">Totals</td><td>4</td>
        <td>5</td><td>3</td><td>182</td><td>96</td><td>278</td>
        <td>55</td><td>68</td><td>0</td><td>2</td></tr>
  </tfoot>
</table>
</body></html>
"""

MOCK_INDEX_HTML = """
<html><body>
<h2>Players B</h2>
<a href="players/B/Ball_Ryan.html">Ryan Ball</a><br/>
<a href="players/B/Bontempelli_Marcus.html">Marcus Bontempelli</a><br/>
<a href="players/B/Brown_Jake.html">Jake Brown</a><br/>
</body></html>
"""

sys.path.insert(0, ".")
import afltables as afl


class TestSeasonIndex(unittest.TestCase):

    def _parse_season(self, html: str, season: int) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        players = []
        for table in soup.find_all("table", class_="sortable"):
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue
                link = cols[1].find("a")
                if not link:
                    continue
                href = link.get("href", "")
                raw  = href.split("/")[-1].replace(".html", "")
                import re
                raw = re.sub(r"\d+$", "", raw)
                players.append({"name": raw.replace("_", " "), "url": afl.STATS_BASE + href})
        return players

    def test_player_count(self):
        self.assertEqual(len(self._parse_season(MOCK_SEASON_HTML, 2026)), 3)

    def test_player_names(self):
        names = [p["name"] for p in self._parse_season(MOCK_SEASON_HTML, 2026)]
        self.assertIn("Bontempelli Marcus", names)
        self.assertIn("Dangerfield Patrick", names)
        self.assertIn("Pendlebury Scott", names)

    def test_player_urls(self):
        players = self._parse_season(MOCK_SEASON_HTML, 2026)
        bont = next(p for p in players if "Bontempelli" in p["name"])
        self.assertIn("Bontempelli_Marcus", bont["url"])
        self.assertTrue(bont["url"].startswith(afl.STATS_BASE))


class TestSeasonStats(unittest.TestCase):

    def _parse_season_df(self, html: str) -> pd.DataFrame:
        dfs = pd.read_html(io.StringIO(html), attrs={"class": "sortable"})
        self.assertGreater(len(dfs), 0)
        return afl._normalise_cols(dfs[0], afl.SEASON_COL_MAP)

    def test_columns_mapped(self):
        df = self._parse_season_df(MOCK_SEASON_HTML)
        for col in ("games", "kicks", "disposals", "marks", "tackles"):
            self.assertIn(col, df.columns)

    def test_row_count(self):
        df = self._parse_season_df(MOCK_SEASON_HTML)
        df = df[pd.to_numeric(df["games"], errors="coerce").notna()]
        self.assertEqual(len(df), 3)

    def test_bontempelli_stats(self):
        df = self._parse_season_df(MOCK_SEASON_HTML)
        row = df.iloc[0]
        self.assertEqual(str(row["games"]), "10")
        self.assertEqual(str(row["kicks"]), "18")
        self.assertEqual(str(row["disposals"]), "28")


class TestPlayerProfile(unittest.TestCase):

    def _parse_profile(self, html: str, season: int | None = None) -> dict:
        import re
        soup = BeautifulSoup(html, "lxml")
        meta: dict = {}
        h1 = soup.find("h1")
        if h1:
            meta["name"] = h1.get_text(strip=True)
        for b in soup.find_all("b"):
            label = b.get_text(strip=True).rstrip(":")
            sibling = b.next_sibling
            val = sibling.strip() if sibling and isinstance(sibling, str) else ""
            if label in ("Born", "Debut", "Height", "Weight", "Position"):
                meta[label.lower()] = val
        all_dfs = pd.read_html(io.StringIO(html))
        totals_df   = afl._normalise_cols(all_dfs[0], afl.SEASON_COL_MAP) if all_dfs else pd.DataFrame()
        averages_df = afl._normalise_cols(all_dfs[1], afl.SEASON_COL_MAP) if len(all_dfs) > 1 else pd.DataFrame()
        if season and "year" in totals_df.columns:
            totals_df   = totals_df[totals_df["year"].astype(str).str.contains(str(season))]
            averages_df = averages_df[averages_df["year"].astype(str).str.contains(str(season))]
        season_pat = str(season) if season else r"\d{4}"
        game_dfs = pd.read_html(io.StringIO(html), match=re.compile(rf"[A-Za-z ]+\s*-\s*{season_pat}"))
        game_rows = []
        for gdf in game_dfs:
            gdf = afl._normalise_cols(gdf, afl.GAME_COL_MAP)
            if "round" in gdf.columns:
                gdf = gdf[~gdf["round"].astype(str).str.lower().isin(["rnd", "nan", ""])]
            game_rows.append(gdf)
        games_df = pd.concat(game_rows, ignore_index=True) if game_rows else pd.DataFrame()
        return {"meta": meta, "totals": totals_df.reset_index(drop=True),
                "averages": averages_df.reset_index(drop=True),
                "games": games_df.reset_index(drop=True)}

    def test_meta_name(self):
        self.assertEqual(self._parse_profile(MOCK_PLAYER_HTML)["meta"]["name"], "Marcus Bontempelli")

    def test_meta_bio(self):
        meta = self._parse_profile(MOCK_PLAYER_HTML)["meta"]
        for key in ("born", "position", "height"):
            self.assertIn(key, meta)

    def test_totals_columns(self):
        df = self._parse_profile(MOCK_PLAYER_HTML)["totals"]
        for col in ("year", "games", "goals", "kicks", "handballs", "disposals",
                    "marks", "tackles", "brownlow_votes"):
            self.assertIn(col, df.columns)

    def test_season_filter(self):
        data = self._parse_profile(MOCK_PLAYER_HTML, season=2026)
        self.assertEqual(len(data["totals"]), 1)
        self.assertIn("2026", str(data["totals"].iloc[0]["year"]))

    def test_game_log_count(self):
        data = self._parse_profile(MOCK_PLAYER_HTML, season=2026)
        games = data["games"][pd.to_numeric(data["games"]["round"], errors="coerce").notna()]
        self.assertEqual(len(games), 10)

    def test_game_log_columns(self):
        df = self._parse_profile(MOCK_PLAYER_HTML, season=2026)["games"]
        for col in ("opponent", "round", "result", "kicks", "handballs",
                    "disposals", "goals", "marks", "tackles"):
            self.assertIn(col, df.columns)

    def test_game_1_stats(self):
        r1 = self._parse_profile(MOCK_PLAYER_HTML, season=2026)["games"].iloc[0]
        self.assertEqual(str(r1["opponent"]), "GWS Giants")
        self.assertEqual(str(r1["round"]), "1")
        self.assertEqual(str(r1["kicks"]), "19")
        self.assertEqual(str(r1["disposals"]), "29")

    def test_season_avg_2026(self):
        avg_row = self._parse_profile(MOCK_PLAYER_HTML, season=2026)["averages"].iloc[0]
        self.assertAlmostEqual(float(avg_row["kicks"]), 18.2)
        self.assertAlmostEqual(float(avg_row["disposals"]), 27.8)


class TestPlayerIndex(unittest.TestCase):

    def _find_url(self, html: str, name: str) -> str:
        import re
        soup = BeautifulSoup(html, "lxml")
        parts = name.strip().split()
        first = "_".join(parts[:-1])
        last  = parts[-1]
        last_initial = last[0].upper()
        slug = f"{last}_{first}"
        pattern = re.compile(rf"players/{last_initial}/{re.escape(slug)}", re.I)
        link = soup.find("a", href=pattern)
        if not link:
            raise LookupError(f"Player {name!r} not found")
        return afl.STATS_BASE + link["href"]

    def test_find_bontempelli(self):
        self.assertIn("Bontempelli_Marcus", self._find_url(MOCK_INDEX_HTML, "Marcus Bontempelli"))

    def test_not_found_raises(self):
        with self.assertRaises(LookupError):
            self._find_url(MOCK_INDEX_HTML, "Nick Riewoldt")


if __name__ == "__main__":
    print("=" * 64)
    print("  AFL Tables parser tests (mock HTML — no network required)")
    print("=" * 64)
    unittest.main(verbosity=2)
