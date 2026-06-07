"""
Forward-looking forum/news sentiment for AFL "value" players.

Punters Mate flags players whose model edge beats the Sportsbet price (od_best /
od_best_F). The pure-stats view already carries recent FORM -- what it can't tell
you is what's being said about the COMING game: previews, the named team, role
and tagging plans, late fitness tests. So this module deliberately fetches and
keeps only forward-looking chatter, anchored on the upcoming fixture (the player
paired with this round's opponent), and drops last-round match reports -- the
stats own momentum better than sentiment does. Each value pick gets a quick read
of what the footy world expects of it this weekend.

SOURCES (all keyless -- the project uses no third-party API keys):
  - Reddit r/AFL : the public search JSON (.../search.json), via cloudscraper.
  - Google News  : the keyless RSS search feed (news.google.com/rss/search).
  - BigFooty     : best-effort scrape of the public XenForo search results.
                   Forum search is anti-bot/often login-gated, so this degrades
                   to "no posts" silently and the feature still runs on the
                   other two sources.

SENTIMENT is scored OFFLINE with VADER (vaderSentiment) plus a small footy-tuned
lexicon (managed/soreness/omitted = bearish; cleared/named/in form = bullish).
VADER is a rule+lexicon model -- no model server, no API key -- which is why it
fits the project's no-keys / works-anywhere constraint. We also raise an
availability flag when injury/selection-risk words appear, since that is the
single most actionable thing the chatter can tell a punter.

CACHING: results are cached to .sentiment_cache.json (gitignored) keyed by
normalised player name + the current date, so repeated builds in a day don't
re-hammer the sources.

CLI:
    python forum_sentiment.py player "Isaac Heeney" --opp "St Kilda" --round 13
    python forum_sentiment.py reddit "Nick Daicos"
    python forum_sentiment.py news   "Marcus Bontempelli"
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import cloudscraper

from lineups import _norm, _strip_mid

# ── tuning ─────────────────────────────────────────────────────────────────────

WINDOW_DAYS = 8           # only chatter from the last ~week is relevant to a slate
PER_SOURCE = 12           # how many raw items to pull per source before filtering
KEEP_ITEMS = 4            # items stored per player for the page (most relevant)
CACHE_PATH = ".sentiment_cache.json"

# Tone label thresholds on VADER's compound score ([-1, 1]).
BULL = 0.12
BEAR = -0.12

# Footy-specific words VADER doesn't know (or reads wrong). Values are on VADER's
# roughly [-4, 4] lexicon scale. These are availability/role/form cues a punter
# weights heavily -- "managed" and "soreness" read neutral to VADER but are bad
# news for a disposal floor.
FOOTY_LEXICON: dict[str, float] = {
    # availability / fitness risk (bearish)
    "managed": -1.6, "management": -1.4, "rested": -1.6, "soreness": -2.2,
    "sore": -1.6, "tightness": -1.8, "niggle": -1.8, "niggling": -1.8,
    "corked": -2.0, "cork": -1.6, "hamstring": -2.4, "calf": -1.8,
    "quad": -1.8, "groin": -2.0, "ankle": -1.8, "knee": -2.0, "shoulder": -1.6,
    "concussion": -3.0, "concussed": -3.0, "hcp": -1.5, "scan": -1.6,
    "scans": -1.6, "setback": -2.6, "doubt": -2.0, "doubtful": -2.4,
    "omitted": -2.6, "dropped": -2.4, "axed": -2.6, "subbed": -1.6,
    "sub": -1.0, "vest": -1.4, "limped": -2.6, "limp": -2.2, "ruled": -1.8,
    "test": -1.0, "tagged": -1.4, "tag": -1.2, "tagger": -1.2, "suspended": -2.6,
    "suspension": -2.4, "ban": -2.2, "banned": -2.4, "withdrawn": -2.4,
    # availability / form upside (bullish)
    "named": 0.9, "cleared": 2.0, "passed": 1.4, "fit": 1.6, "available": 1.6,
    "returns": 1.6, "return": 1.2, "recall": 1.4, "recalled": 1.6, "back": 0.8,
    "dominant": 2.4, "dominated": 2.4, "racked": 1.8, "ton": 1.6, "tonned": 2.0,
    "bog": 2.4, "untagged": 1.6, "freed": 1.6, "inform": 2.0, "midfield": 0.6,
    "onball": 1.0, "pinch": 0.6, "fires": 2.0, "starring": 2.4, "stars": 1.6,
}

# Words that trip an explicit availability warning regardless of overall tone.
RISK_WORDS = re.compile(
    r"\b(manage[ds]?|rest(?:ed|ing)?|soreness|sore|niggl\w*|cork\w*|hamstring|"
    r"calf|quad|groin|ankle|knee|shoulder|concus\w*|scan\w*|setback|doubt\w*|"
    r"omitted|dropped|axed|subbed|limp\w*|ruled out|fitness test|suspen\w*|"
    r"ban(?:ned)?|withdrawn|injur\w*|tagg\w*)\b",
    re.I,
)

# ── forward-looking gate ────────────────────────────────────────────────────────
# The point of the layer is what's being said about the COMING game, not a recap of
# last round (the stats already carry recent form). We anchor on the upcoming
# fixture: an item counts as forward-looking if it names this week's opponent, or
# carries a selection/role/availability marker -- and is not explicitly about a
# different round or a finished result.

# CSV club name -> search/match aliases (full name + common nicknames). Used both
# to build opponent-anchored queries and to detect the opponent in an item.
CLUB_ALIASES: dict[str, list[str]] = {
    "Adelaide": ["adelaide", "crows"],
    "Brisbane Lions": ["brisbane", "lions"],
    "Carlton": ["carlton", "blues"],
    "Collingwood": ["collingwood", "magpies", "pies"],
    "Essendon": ["essendon", "bombers", "dons"],
    "Fremantle": ["fremantle", "dockers", "freo"],
    "Geelong": ["geelong", "cats"],
    "Gold Coast": ["gold coast", "suns"],
    "Greater Western Sydney": ["gws", "giants", "greater western sydney"],
    "Hawthorn": ["hawthorn", "hawks"],
    "Melbourne": ["melbourne", "demons", "dees"],
    "North Melbourne": ["north melbourne", "kangaroos", "roos"],
    "Port Adelaide": ["port adelaide", "power"],
    "Richmond": ["richmond", "tigers"],
    "St Kilda": ["st kilda", "saints"],
    "Sydney": ["sydney", "swans"],
    "West Coast": ["west coast", "eagles"],
    "Western Bulldogs": ["western bulldogs", "bulldogs", "dogs"],
}

# Selection / role / availability cues that mark an item as about the COMING game
# even when it doesn't spell out the opponent ("set to collide", "named", "test").
FWD_MARKER = re.compile(
    r"\b(preview|team[s]? named|named to|to face|line ?up|ins and outs|"
    r"selection|set to|tipped to|recall\w*|return\w*|comes? in|in doubt|"
    r"fitness test|race to be fit|will (?:play|face|line)|expected to|"
    r"tag\w*|changes?|game day|this week|round \d+ preview)\b", re.I)

# Finished-result / recap markers -- a match report, not a preview.
BACK_MARKER = re.compile(
    r"\b(beat|defeat\w*|def\.|wins?|won|lost|loss|downed|thrash\w*|"
    r"match report|best on ground|polls?|votes?|wrap|run riot|"
    r"kicked \d+|\d+[- ]goal|haul)\b", re.I)

_ROUND_RE = re.compile(r"\b(?:round|rd|r)\s*\.?\s*(\d{1,2})\b", re.I)


def opponent_aliases(team: str | None) -> list[str]:
    return CLUB_ALIASES.get(team or "", [])


def _round_nums(text: str) -> set[int]:
    return {int(m) for m in _ROUND_RE.findall(text or "")}


def is_forward(item: dict, opp_aliases: list[str], round_no: int | None) -> bool:
    """True if the item is about the coming game (not last round / another round).

    Broad rule: explicit other-round references are dropped; otherwise an item is
    kept when it names this week's opponent, or carries a forward selection/role
    marker without being a finished-result recap."""
    text = _norm(f"{item.get('title','')} {item.get('body','')}")
    if round_no is not None:
        rounds = _round_nums(text)
        if rounds and round_no not in rounds:
            return False                      # explicitly about a different round
    if any(a in text for a in opp_aliases):
        return True                           # names this week's opponent
    if RISK_WORDS.search(text):
        return True                           # injury/selection/tag = forward-relevant
    return bool(FWD_MARKER.search(text) and not BACK_MARKER.search(text))


# ── sentiment scoring ───────────────────────────────────────────────────────────

_ANALYZER = None


def _analyzer():
    """Lazily build a VADER analyzer with the footy lexicon folded in.

    Returns None if vaderSentiment isn't installed, so callers degrade to "no
    sentiment" rather than crashing a page build."""
    global _ANALYZER
    if _ANALYZER is None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        except ImportError:
            return None
        a = SentimentIntensityAnalyzer()
        a.lexicon.update(FOOTY_LEXICON)
        _ANALYZER = a
    return _ANALYZER


def score_text(text: str) -> float | None:
    """VADER compound score in [-1, 1], or None if VADER is unavailable."""
    a = _analyzer()
    if a is None:
        return None
    return a.polarity_scores(text or "")["compound"]


def _label(compound: float) -> str:
    if compound >= BULL:
        return "bullish"
    if compound <= BEAR:
        return "bearish"
    return "neutral"


# ── fetchers (each returns a list of raw item dicts; never raises) ──────────────

REDDIT_UA = "puntersmate/1.0 (AFL stats helper)"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def make_scraper():
    return cloudscraper.create_scraper(browser={"custom": "Chrome"})


def _within_window(ts: float | None) -> bool:
    if ts is None:
        return True   # undated -> keep (news without a parseable date)
    age = time.time() - ts
    return 0 <= age <= WINDOW_DAYS * 86400


def _clean(s: str) -> str:
    """Strip HTML tags + unescape entities + collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    # Reddit's RSS emits a stray cp1252 apostrophe that decodes to U+FFFD; restore it.
    s = html.unescape(s).replace("�", "'")
    return re.sub(r"\s+", " ", s).strip()


def _iso_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fetch_reddit(query: str, scraper=None, limit: int = PER_SOURCE) -> list[dict]:
    """Recent r/AFL posts mentioning the query.

    Reddit hard-403s the unauthenticated `search.json` endpoint, but the Atom
    `search.rss` feed is still public, so we parse that."""
    scraper = scraper or make_scraper()
    url = ("https://www.reddit.com/r/AFL/search.rss?"
           f"q={quote_plus(query)}&restrict_sr=on&sort=new&t=week")
    try:
        r = scraper.get(url, headers={"User-Agent": REDDIT_UA}, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []
    out = []
    for e in root.findall("a:entry", _ATOM):
        link_el = e.find("a:link", _ATOM)
        ts = _iso_ts(e.findtext("a:updated", None, _ATOM)
                     or e.findtext("a:published", None, _ATOM))
        if not _within_window(ts):
            continue
        out.append({
            "source": "reddit",
            "title": _clean(e.findtext("a:title", "", _ATOM)),
            "body": _clean(e.findtext("a:content", "", _ATOM))[:600],
            "url": link_el.get("href") if link_el is not None else "",
            "ts": ts,
        })
        if len(out) >= limit:
            break
    return out


def fetch_news(query: str, scraper=None, limit: int = PER_SOURCE) -> list[dict]:
    """Recent AFL news for the query, via the keyless Google News RSS feed."""
    scraper = scraper or make_scraper()
    q = quote_plus(f'{query} AFL')
    url = (f"https://news.google.com/rss/search?q={q}+when:{WINDOW_DAYS}d"
           "&hl=en-AU&gl=AU&ceid=AU:en")
    try:
        r = scraper.get(url, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        ts = None
        if pub:
            for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
                try:
                    ts = datetime.strptime(pub, fmt).replace(
                        tzinfo=timezone.utc).timestamp()
                    break
                except ValueError:
                    continue
        if not _within_window(ts):
            continue
        # Google News appends " - Publisher" to the title; split it out.
        src_name = ""
        if " - " in title:
            title, _, src_name = title.rpartition(" - ")
        out.append({
            "source": "news",
            "title": title.strip(),
            "body": src_name.strip(),
            "url": link,
            "ts": ts,
        })
        if len(out) >= limit:
            break
    return out


def fetch_bigfooty(query: str, scraper=None, limit: int = PER_SOURCE) -> list[dict]:
    """Best-effort scrape of BigFooty's public XenForo search results.

    Forum search is frequently anti-bot or login-gated; on any failure (or an
    unexpected page shape) this returns [] and the feature carries on with the
    other sources. Never raises."""
    scraper = scraper or make_scraper()
    # Full-text (not title-only): a player's name lives in post bodies, not thread
    # titles. We keep each result's snippet -- that's the matched text we score and
    # relevance-check against, and the only forum text the page surfaces.
    url = ("https://www.bigfooty.com/forum/search/search?"
           f"q={quote_plus(query)}&o=date")
    try:
        r = scraper.get(url, timeout=20)
        if r.status_code != 200 or "contentRow" not in r.text:
            return []
    except Exception:
        return []
    out = []
    row = re.compile(
        r'<h3 class="contentRow-title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<div class="contentRow-snippet">(.*?)</div>', re.S)
    for m in row.finditer(r.text):
        href, title_html, snippet = m.group(1), m.group(2), m.group(3)
        # The coloured XenForo prefix chips ("Preview", "Game Day", "Changes",
        # "Team") are a strong forward-looking signal -- keep their text in the body
        # for classification, but strip them from the displayed title.
        labels = " ".join(_clean(x) for x in
                          re.findall(r'<span class="label[^>]*>(.*?)</span>', title_html, re.S))
        title_html = re.sub(r'<span class="label[^>]*>.*?</span>', "", title_html, flags=re.S)
        title = _clean(title_html)
        if not title:
            continue
        if href.startswith("/"):
            href = "https://www.bigfooty.com" + href
        out.append({"source": "bigfooty", "title": title,
                    "body": (labels + " " + _clean(snippet)).strip()[:600],
                    "url": href, "ts": None})
        if len(out) >= limit:
            break
    return out


# ── aggregation ─────────────────────────────────────────────────────────────────

def _relevant(item: dict, surname: str, given: str) -> bool:
    """Keep an item only if it's actually ABOUT the player (kills generic AFL
    headlines a broad query drags in).

    Per source: a Reddit thread's TITLE is its topic, so a body-only mention there
    is almost always an aside in a multi-player debate -- require the surname in the
    title. News articles are single-subject and BigFooty's snippet is the text
    around the search hit, so for those a title-or-body match is reliable."""
    title = _norm(item.get("title", ""))
    hay = title if item.get("source") == "reddit" else _norm(
        f"{item.get('title','')} {item.get('body','')}")
    sn = _norm(surname)
    if sn and sn in hay:
        return True
    gn = _norm(given)
    return bool(gn and sn and gn in hay and sn in hay)


def player_sentiment(name: str, opponent: str | None = None,
                     round_no: int | None = None, scraper=None,
                     sources=("reddit", "news", "bigfooty")) -> dict | None:
    """Aggregate FORWARD-LOOKING chatter about a player's coming game into a tone
    read.

    `name` is the CSV "Surname, Given" form; `opponent` is the CSV club name they
    face this round and `round_no` the round number -- both anchor the fetch on the
    upcoming fixture rather than the player in isolation, and drive the forward gate
    (see is_forward). We deliberately do NOT surface last-round match reports: the
    stats already carry recent form. Returns a dict ready to embed
      {label, compound, n, by_source, availability, items:[...]}
    or None if no forward-looking, player-relevant chatter was found / VADER missing.
    """
    if _analyzer() is None:
        return None
    sur, _, giv = name.partition(", ")
    giv = _strip_mid(giv)
    full = f"{giv} {sur}".strip()
    scraper = scraper or make_scraper()
    opp_aliases = opponent_aliases(opponent)

    # Anchor each source on the coming game: pair the player with the opponent, and
    # ask news explicitly for a preview, so the queries lean forward before the gate.
    queries = {
        "news": [f'"{full}" {opponent}' if opponent else full, f'"{full}" preview'],
        "bigfooty": [f'{full} {opponent}' if opponent else full],
        "reddit": [full],
    }
    fetchers = {"reddit": fetch_reddit, "news": fetch_news, "bigfooty": fetch_bigfooty}
    raw: list[dict] = []
    for s in sources:
        for q in queries.get(s, [full]):
            try:
                raw += fetchers[s](q, scraper)
            except Exception:
                continue

    items, seen = [], set()
    for it in raw:
        if not _relevant(it, sur, giv):
            continue                          # must actually name the player
        if not is_forward(it, opp_aliases, round_no):
            continue                          # must be about the coming game
        key = (it["source"], it["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        blob = f"{it['title']}. {it.get('body','')}"
        it["score"] = score_text(blob)
        it["risk"] = bool(RISK_WORDS.search(blob))
        it["opp"] = any(a in _norm(blob) for a in opp_aliases)
        items.append(it)

    if not items:
        return None

    scores = [i["score"] for i in items if i["score"] is not None]
    compound = round(sum(scores) / len(scores), 3) if scores else 0.0
    availability = any(i["risk"] for i in items)
    by_source: dict[str, int] = {}
    for i in items:
        by_source[i["source"]] = by_source.get(i["source"], 0) + 1

    # Keep the most decisive items for the page: availability flags first, then
    # items that actually name this week's opponent (most game-specific), then
    # strongest tone, then most recent.
    items.sort(key=lambda i: (i["risk"], i["opp"], abs(i["score"] or 0), i["ts"] or 0),
               reverse=True)
    kept = []
    for i in items[:KEEP_ITEMS]:
        when = ""
        if i["ts"]:
            when = datetime.fromtimestamp(i["ts"], tz=timezone.utc).strftime("%b %d")
        kept.append({"source": i["source"], "title": i["title"][:140],
                     "url": i["url"], "score": round(i["score"], 2) if i["score"] is not None else None,
                     "risk": i["risk"], "opp": i["opp"], "when": when})

    return {
        "label": _label(compound),
        "compound": compound,
        "n": len(items),
        "by_source": by_source,
        "availability": availability,
        "items": kept,
    }


# ── cache ────────────────────────────────────────────────────────────────────

def _load_cache(path: str = CACHE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict, path: str = CACHE_PATH) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


def cached_player_sentiment(name: str, opponent: str | None = None,
                            round_no: int | None = None, scraper=None,
                            cache: dict | None = None, today: str | None = None,
                            **kw) -> dict | None:
    """player_sentiment with a same-day disk cache keyed by name + opponent.

    Pass a shared `cache` dict (loaded once per build) to batch reads/writes; if
    omitted, this loads and saves the file itself per call. The key includes the
    opponent so a re-fixtured matchup re-fetches rather than serving a stale read."""
    today = today or str(date.today())
    own_cache = cache is None
    cache = cache if cache is not None else _load_cache()
    key = f"{_norm(name)}|{_norm(opponent or '')}"
    hit = cache.get(key)
    if hit and hit.get("date") == today:
        return hit.get("payload")
    payload = player_sentiment(name, opponent, round_no, scraper, **kw)
    cache[key] = {"date": today, "payload": payload}
    if own_cache:
        _save_cache(cache)
    return payload


# ── CLI ────────────────────────────────────────────────────────────────────────

def _to_csv_name(s: str) -> str:
    """Accept 'Errol Gulden' or 'Gulden, Errol'; return the CSV 'Surname, Given'."""
    if "," in s:
        return s
    parts = s.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else s


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="AFL forum/news sentiment for a player.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("player", help="forward-looking sentiment for the coming game")
    pp.add_argument("name")
    pp.add_argument("--opp", help="opponent club (CSV name) this round, e.g. 'St Kilda'")
    pp.add_argument("--round", type=int, help="round number (drops other-round items)")
    pp.add_argument("--no-cache", action="store_true")
    for src in ("reddit", "news", "bigfooty"):
        sp = sub.add_parser(src, help=f"raw {src} items only")
        sp.add_argument("name")
    args = p.parse_args(argv)
    scraper = make_scraper()

    if args.cmd == "player":
        if _analyzer() is None:
            print("vaderSentiment not installed -- pip install vaderSentiment", file=sys.stderr)
            return 2
        name = _to_csv_name(args.name)
        if args.no_cache:
            res = player_sentiment(name, args.opp, args.round, scraper)
        else:
            res = cached_player_sentiment(name, args.opp, args.round, scraper)
        vs = f" (vs {args.opp})" if args.opp else ""
        if not res:
            print(f"No forward-looking chatter for {args.name}{vs}.")
            return 0
        print(f"{args.name}{vs}: {res['label'].upper()} (compound {res['compound']}, "
              f"{res['n']} mentions {res['by_source']}"
              f"{' | AVAILABILITY FLAG' if res['availability'] else ''})\n")
        for i in res["items"]:
            tag = "!" if i["risk"] else ("@" if i.get("opp") else " ")
            print(f" [{i['source']:<8}] {tag} {i['score']:+.2f}  {i['when']:<7} {i['title']}")
            print(f"            {i['url']}")
        return 0

    # raw source dumps
    name = _to_csv_name(args.name)
    sur, _, giv = name.partition(", ")
    full = f"{_strip_mid(giv)} {sur}".strip()
    fn = {"reddit": fetch_reddit, "news": fetch_news, "bigfooty": fetch_bigfooty}[args.cmd]
    items = fn(full, scraper)
    print(f"{len(items)} raw {args.cmd} items for '{full}':\n")
    for it in items:
        print(f" - {it['title']}\n   {it['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
