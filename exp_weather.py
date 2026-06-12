"""
Weather backtest — the one BRAINSTORM.md family (§6) never tested, for lack of a
data source. Open-Meteo's historical archive is free and keyless, so every game
2022-2026 is now testable.

Pipeline:
  1. CSV player-game -> venue + bounce unixtime via venues._row_lut (the
     chronological-by-opponent join that survives the afltables round offset).
  2. Venue -> lat/lon (hardcoded for the ~19 AFL venues).
  3. Open-Meteo archive: hourly precipitation / wind / temperature per venue,
     one cached call per venue (weather_cache/).
  4. Features per game: rain during the game (bounce..+3h), rain in the 6h before
     (wet ground), mean wind and temperature during the game.
  5. Tests:
     a. League sanity — do wet games actually compress team disposals/marks here?
     b. Player level — does weather explain the residual the blend leaves behind?
        (corr + out-of-sample fitted coefficient, disposals and fantasy)

Note on sample: weather is shared by all ~44 players in a game, so the effective
sample is ~1,900 games, not 34k player-rows; player-level correlations inherit
that clustering.
"""
import argparse, json, os
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests

import matchup as M
import venues as V

FW = M.FORM_WINDOWS
CACHE = "weather_cache"
ARCHIVE = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           "&start_date={start}&end_date={end}"
           "&hourly=precipitation,wind_speed_10m,temperature_2m&timezone=UTC")

# Approximate centre coordinates per Squiggle venue name (weather-grade precision).
VENUE_LATLON = {
    "M.C.G.": (-37.8200, 144.9834), "Docklands": (-37.8166, 144.9475),
    "Kardinia Park": (-38.1580, 144.3546), "Eureka Stadium": (-37.5395, 143.8508),
    "Adelaide Oval": (-34.9156, 138.5961), "Norwood Oval": (-34.9206, 138.6325),
    "Barossa Park": (-34.6020, 138.8910), "Adelaide Hills": (-35.0667, 138.8560),
    "Perth Stadium": (-31.9511, 115.8890), "Hands Oval": (-33.3333, 115.6500),
    "S.C.G.": (-33.8915, 151.2245), "Sydney Showground": (-33.8430, 151.0680),
    "Gabba": (-27.4858, 153.0381), "Carrara": (-28.0064, 153.3670),
    "York Park": (-41.4260, 147.1390), "Bellerive Oval": (-42.8773, 147.3733),
    "Manuka Oval": (-35.3180, 149.1345), "Marrara Oval": (-12.3992, 130.8872),
    "Traeger Park": (-23.7080, 133.8740), "Cazalys Stadium": (-16.9358, 145.7490),
    "Cazaly's Stadium": (-16.9358, 145.7490),
}


def venue_weather(venue):
    """Hourly UTC series for a venue, cached to disk: {iso_hour: (precip, wind, temp)}."""
    lat, lon = VENUE_LATLON[venue]
    path = os.path.join(CACHE, venue.replace(".", "").replace("'", "").replace(" ", "_") + ".json")
    if os.path.exists(path):
        js = json.load(open(path, encoding="utf-8"))
    else:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = ARCHIVE.format(lat=lat, lon=lon, start="2022-01-01", end=end)
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        js = r.json()
        os.makedirs(CACHE, exist_ok=True)
        json.dump(js, open(path, "w", encoding="utf-8"))
    h = js["hourly"]
    return {t: (p, w, tp) for t, p, w, tp in zip(
        h["time"], h["precipitation"], h["wind_speed_10m"], h["temperature_2m"])}


def game_features(venue, unixtime, wx):
    """(rain_game_mm, rain_pre6h_mm, wind_kmh, temp_c) around the bounce."""
    if unixtime is None:
        return None
    t0 = datetime.fromtimestamp(unixtime, tz=timezone.utc).replace(minute=0, second=0)
    def iso(dt): return dt.strftime("%Y-%m-%dT%H:00")
    from datetime import timedelta
    game_h = [iso(t0 + timedelta(hours=k)) for k in range(0, 3)]
    pre_h = [iso(t0 - timedelta(hours=k)) for k in range(1, 7)]
    g = [wx.get(t) for t in game_h]
    p = [wx.get(t) for t in pre_h]
    g = [x for x in g if x and x[0] is not None]
    p = [x for x in p if x and x[0] is not None]
    if not g:
        return None
    return (float(sum(x[0] for x in g)), float(sum(x[0] for x in p)) if p else 0.0,
            float(np.mean([x[1] for x in g])), float(np.mean([x[2] for x in g])))


def _h2h(prior, opp, season):
    g = [r for r in prior if r["opponent"] == opp]
    if not g:
        return np.nan
    w = np.array([max(1, r["season"] - (season - 3)) for r in g], float)
    return float((np.array([r["disposals"] for r in g], float) * w).sum() / w.sum())


def cv_gain(d, feat, target_resid, k=5, seed=0):
    """OOS MAE delta from adding b*feature to the baseline (b fit per train fold)."""
    d = d.dropna(subset=[feat]).reset_index(drop=True)
    base = d["base"].to_numpy(); act = d["act"].to_numpy(); x = d[feat].to_numpy()
    resid = act - base
    idx = np.random.default_rng(seed).permutation(len(d))
    folds = np.array_split(idx, k); be, ae = [], []
    for j in range(k):
        te = folds[j]; tr = np.concatenate([folds[m] for m in range(k) if m != j])
        xt = x[tr] - x[tr].mean()
        b = float((xt @ resid[tr]) / (xt @ xt)) if (xt @ xt) > 0 else 0.0
        be.append(np.abs(base[te] - act[te]))
        ae.append(np.abs(base[te] + b * (x[te] - x[tr].mean()) - act[te]))
    return np.concatenate(be).mean(), np.concatenate(ae).mean(), len(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="games_2022_2026.csv")
    args = ap.parse_args()
    df = M.load(args.csv)
    df = df[df["disposals"].notna()].sort_values(["season", "round"]).reset_index(drop=True)

    # 1-2) venue + unixtime per (season, team, round), then weather per game
    lut = V._row_lut(df, verify=True)
    keys = df[["season", "team", "round"]].drop_duplicates()
    need_venues = set()
    for _, r in keys.iterrows():
        info = lut.get((int(r["season"]), r["team"], r["round"]))
        if info and info["venue"] in VENUE_LATLON:
            need_venues.add(info["venue"])
    unmapped = {info["venue"] for k in lut for info in [lut[k]] if info} - set(VENUE_LATLON)
    if unmapped:
        print(f"  (unmapped venues skipped: {sorted(unmapped)})")
    wx_by_venue = {v: venue_weather(v) for v in sorted(need_venues)}

    feat_by_key = {}
    for k, info in lut.items():
        if not info or info["venue"] not in wx_by_venue:
            continue
        f = game_features(info["venue"], info.get("unixtime"), wx_by_venue[info["venue"]])
        if f:
            feat_by_key[k] = f

    df["_k"] = list(zip(df["season"].astype(int), df["team"], df["round"]))
    have = df["_k"].map(lambda k: k in feat_by_key)
    print(f"\n  weather coverage: {have.mean()*100:.1f}% of {len(df)} player-rows "
          f"({len(feat_by_key)} team-games located)")

    # a) league sanity: team totals by rain bucket
    tg = df[have].groupby("_k").agg(disp=("disposals", "sum"), marks=("marks", "sum"),
                                    kicks=("kicks", "sum"), n=("disposals", "size"))
    tg["rain"] = [feat_by_key[k][0] for k in tg.index]
    tg["wind"] = [feat_by_key[k][2] for k in tg.index]
    buckets = [("dry (0mm)", tg["rain"] == 0), ("light (0-2mm)", (tg["rain"] > 0) & (tg["rain"] < 2)),
               ("wet (2mm+)", tg["rain"] >= 2)]
    print(f"\n  league sanity - per-team-game totals by in-game rain:")
    print(f"  {'bucket':<16}{'games':>7}{'disposals':>11}{'marks':>8}{'kick%':>8}")
    for name, m in buckets:
        s = tg[m]
        if len(s):
            print(f"  {name:<16}{len(s):>7}{s['disp'].mean():>11.1f}{s['marks'].mean():>8.1f}"
                  f"{(s['kicks'].sum()/s['disp'].sum())*100:>7.1f}%")
    hi = tg[tg["wind"] >= 30]; lo = tg[tg["wind"] < 15]
    print(f"  windy (30+km/h): {len(hi)} games, disposals {hi['disp'].mean():.1f}  |  "
          f"calm (<15): {len(lo)} games, {lo['disp'].mean():.1f}")

    # b) player-level residual tests, walk-forward baseline
    phist = defaultdict(list)
    rows = []
    for rec in df.to_dict("records"):
        s, opp = rec["season"], rec["opponent"]
        key = (rec["player"], rec["team"]); prior = phist[key]
        sp = [x for x in prior if x["season"] == s]
        f = feat_by_key.get(rec["_k"])
        if f and len(sp) >= 3:
            d = [x["disposals"] for x in sp]
            windows = {f"L{w}": float(np.mean(d[-w:])) for w in FW}
            h2h = _h2h(prior, opp, s)
            base = M.project(windows, h2h, float(np.mean(d)), pd.notna(h2h))
            fan = [x["fantasy"] for x in sp if pd.notna(x["fantasy"])]
            fbase = np.nan
            if len(fan) >= 3:
                fw = {f"L{w}": float(np.mean(fan[-w:])) for w in FW}
                fbase = M.project(fw, np.nan, float(np.mean(fan)), False)
            rows.append({"act": float(rec["disposals"]), "base": base,
                         "fact": float(rec["fantasy"]) if pd.notna(rec["fantasy"]) else np.nan,
                         "fbase": fbase,
                         "rain": f[0], "pre_rain": f[1], "wind": f[2], "temp": f[3],
                         "wet": float(f[0] >= 2.0)})
        phist[key].append(rec)
    r = pd.DataFrame(rows)
    print(f"\n  player-level: {len(r)} held-out rows with weather")
    resid = r["act"] - r["base"]
    for feat in ["rain", "pre_rain", "wind", "temp", "wet"]:
        print(f"    corr({feat:8s}, disposal residual) = {np.corrcoef(r[feat], resid)[0,1]:+.3f}")

    print(f"\n  out-of-sample gain from adding each weather term (disposals):")
    for feat in ["rain", "pre_rain", "wind", "wet"]:
        b, a, n = cv_gain(r, feat, resid)
        d_ = a - b
        tag = "improves" if d_ < -1e-3 else ("~no gain" if abs(d_) <= 1e-3 else "worse")
        print(f"    +{feat:<9} {b:.3f} -> {a:.3f}  ({d_:+.3f}, {d_/b*100:+.1f}%)  {tag}")

    rf = r.dropna(subset=["fact", "fbase"]).copy()
    rf["base"], rf["act"] = rf["fbase"], rf["fact"]
    fresid = rf["act"] - rf["base"]
    print(f"\n  fantasy ({len(rf)} rows):")
    for feat in ["rain", "wind", "wet"]:
        print(f"    corr({feat:8s}, fantasy residual) = {np.corrcoef(rf[feat], fresid)[0,1]:+.3f}")
    for feat in ["rain", "wind", "wet"]:
        b, a, n = cv_gain(rf, feat, fresid)
        d_ = a - b
        tag = "improves" if d_ < -1e-3 else ("~no gain" if abs(d_) <= 1e-3 else "worse")
        print(f"    +{feat:<9} {b:.3f} -> {a:.3f}  ({d_:+.3f}, {d_/b*100:+.1f}%)  {tag}")


if __name__ == "__main__":
    main()
