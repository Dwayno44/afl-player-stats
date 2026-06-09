import json, math, re, lineups as L, requests
from statistics import NormalDist
ND = NormalDist()
FR = 0.50  # fraction of game remaining (halftime)

# projections (disposal + fantasy) from the built page
data = json.loads(re.search(r'const DATA = (\{.*?\});', open('docs/index.html', encoding='utf-8').read(), re.S).group(1))
snap = {}
for g in data['games']:
    if g['round'] == 13 and g['home'] == 'Collingwood':
        for side in ('home_view', 'away_view'):
            for r in g[side]:
                snap[r['player']] = r


def find(sur, giv=None):
    for k, r in snap.items():
        s, _, gg = k.partition(', ')
        if s == sur and (giv is None or gg.startswith(giv)):
            return r
    return None


token = L.get_token(verify=True); cid = L.compseason_id(2026, token, True)
h = {'User-Agent': L.UA, 'x-media-mis-token': token}
cur = {}
for m in L._matches(cid, 13, token, True):
    if 'Collingwood' not in m['home']['team']['name']:
        continue
    js = requests.get(f"https://api.afl.com.au/cfs/afl/playerStats/match/{m['providerId']}",
                      headers=h, timeout=30, verify=True).json()
    for sd in ('homeTeamPlayerStats', 'awayTeamPlayerStats'):
        for p in js[sd]:
            nm = p['player']['player']['player']['playerName']; st = p['playerStats'].get('stats') or {}
            cur[(nm['surname'], nm['givenName'])] = (st.get('disposals') or 0, st.get('dreamTeamPoints') or 0)
    break


def p_clear(sur, line, stat='D', giv=None):
    r = find(sur, giv)
    c = next((v for (s, g), v in cur.items() if s == sur and (giv is None or g.startswith(giv))), None)
    if not r or c is None:
        return (None, None)
    now = c[0] if stat == 'D' else c[1]
    proj = r.get('D_proj') if stat == 'D' else r.get('F_proj')
    sig = r.get('D_sigma') if stat == 'D' else r.get('F_sigma')
    if proj is None or not sig:
        return (now, None)
    mu, sd = proj * FR, sig * math.sqrt(FR)
    need = line - now
    p = 1.0 if need <= 0 else (1 - ND.cdf((need - mu) / sd))
    return (now, max(0.0, min(1.0, p)))


print('BET 1  (7-leg multi, potential $52.86, cash out $5.28) -- ALL must win')
legs1 = [('Langford', 11, 'D', None), ('Windsor', 10, 'D', None), ('Schultz', 12, 'D', None),
         ('Cameron', 12, 'D', 'Darcy'), ('Bowey', 75, 'F', None), ('McCreery', 11, 'D', None),
         ('Howe', 13, 'D', None)]
P1 = 1.0
for sur, line, stat, giv in legs1:
    now, p = p_clear(sur, line, stat, giv)
    lab = 'WON ' if p == 1.0 else (f'{p*100:4.0f}%' if p is not None else ' n/a')
    unit = 'fant' if stat == 'F' else 'disp'
    print(f'  {sur:<10}{line}+ {unit}   now {(now if now is not None else 0):>3.0f}   P {lab}')
    if p is not None:
        P1 *= p
print(f'  -> P(all) = {P1*100:.2f}%   running EV = ${P1*52.86:.2f}   vs CASH OUT $5.28')
print()
print('BET 2  (SGM, potential $80, cash out $8.28) -- 4 pending must win (+2 goals already WON)')
legs2 = [('Gawn', 18, 'D', None), ('Bowey', 20, 'D', None), ('Crisp', 18, 'D', None), ('Daicos', 28, 'D', 'Nick')]
P2 = 1.0
for sur, line, stat, giv in legs2:
    now, p = p_clear(sur, line, stat, giv)
    print(f'  {sur:<10}{line}+ disp   now {now:>3.0f}   P {p*100:4.0f}%')
    P2 *= p
print(f'  -> P(all 4) = {P2*100:.2f}%   running EV = ${P2*80:.2f}   vs CASH OUT $8.28')
