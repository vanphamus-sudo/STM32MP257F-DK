"""Read-only E.212 directory and LTE MHz labels. No registration changes here."""
from functools import lru_cache
import json
from pathlib import Path
import re

# Band: DL low/high MHz, DL EARFCN first/last, UL low/high MHz.
# 3GPP TS 36.101 tables 5.5-1 and 5.7.3-1 (ETSI release 15.6).
# Only catalogued bands are labelled; unknown bands/channels are not guessed.
LTE = {
    1:(2110,2170,0,599,1920,1980), 2:(1930,1990,600,1199,1850,1910),
    3:(1805,1880,1200,1949,1710,1785), 4:(2110,2155,1950,2399,1710,1755),
    5:(869,894,2400,2649,824,849), 6:(875,885,2650,2749,830,840),
    7:(2620,2690,2750,3449,2500,2570), 8:(925,960,3450,3799,880,915),
    12:(729,746,5010,5179,699,716), 13:(746,756,5180,5279,777,787),
    14:(758,768,5280,5379,788,798), 17:(734,746,5730,5849,704,716),
    18:(860,875,5850,5999,815,830), 19:(875,890,6000,6149,830,845),
    20:(791,821,6150,6449,832,862), 25:(1930,1995,8040,8689,1850,1915),
    26:(859,894,8690,9039,814,849), 28:(758,803,9210,9659,703,748),
    29:(717,728,9660,9769,None,None), 30:(2350,2360,9770,9869,2305,2315),
    32:(1452,1496,9920,10359,None,None), 34:(2010,2025,36200,36349,2010,2025),
    38:(2570,2620,37750,38249,2570,2620), 39:(1880,1920,38250,38649,1880,1920),
    40:(2300,2400,38650,39649,2300,2400), 41:(2496,2690,39650,41589,2496,2690),
    42:(3400,3600,41590,43589,3400,3600), 43:(3600,3800,43590,45589,3600,3800),
    46:(5150,5925,46790,54539,5150,5925), 48:(3550,3700,55240,56739,3550,3700),
    66:(2110,2200,66436,67335,1710,1780), 71:(617,652,68586,68935,663,698),
}


def band_label(band, earfcn=None):
    band = int(band)
    label = 'LTE BAND ' + str(band)
    values = LTE.get(band)
    if not values:
        return label + ' (MHz range not catalogued)'
    low, high, first, last, ul_low, ul_high = values
    label += f': downlink {low:g}-{high:g} MHz'
    if ul_low is not None:
        label += f'; uplink {ul_low:g}-{ul_high:g} MHz'
    else:
        label += '; downlink-only band'
    if type(earfcn) is int and first <= earfcn <= last:
        frequency = low + .1 * (earfcn - first)
        label += f'; current downlink {frequency:g} MHz'
    return label


def band_options(supported):
    options = []
    for name in supported:
        match = re.fullmatch(r'eutran-(\d+)', name)
        if match:
            options.append(dict(value=name, label=band_label(int(match[1]))))
    return sorted(options, key=lambda item:int(item['value'].split('-')[1]))


@lru_cache(maxsize=1)
def directory():
    return json.loads((Path(__file__).resolve().parent / 'mobile-networks.json').read_text(encoding='utf-8'))


def choices(current=None, saved=''):
    # Copy before adding live/unknown codes; never modify the cached directory.
    data = json.loads(json.dumps(directory()))
    countries = {entry['mcc']:entry for entry in data['countries']}
    current = current or {}
    for code, name in [(saved, ''), (current.get('code', ''), current.get('name', ''))]:
        if not isinstance(code, str) or not re.fullmatch(r'\d{5,6}', code):
            continue
        mcc, mnc = code[:3], code[3:]
        country = countries.setdefault(mcc, dict(mcc=mcc, name='Other / reported network area', networks=[]))
        found = next((n for n in country['networks'] if n['mnc']==mnc), None)
        if found is None:
            country['networks'].append(dict(mnc=mnc, name=name or 'Saved network (name unavailable)'))
        elif name:
            found['name'] = name  # Modem's current broadcast name takes precedence.
    data['countries'] = sorted(countries.values(), key=lambda c:(c['name'].casefold(),c['mcc']))
    data['current'] = current
    return data
