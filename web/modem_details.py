"""Read-only LTE status. Identifiers are returned only through the authenticated API."""
import csv
import json
import math
import re
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen
import cellular_info

FIELDS = ('selection', 'model', 'uptime', 'status', 'network', 'signal', 'ip', 'dns',
          'sim_status', 'iccid', 'imsi', 'imei', 'lac', 'cell_id', 'rsrp', 'rsrq',
          'sinr', 'operator', 'band', 'revision', 'cell')


def clean(value):
    return value if value not in (None, '', '--', 'unknown') else None


def query(*args):
    try:
        return json.loads(subprocess.check_output(['mmcli', *args, '-J'], text=True,
                          stderr=subprocess.DEVNULL, timeout=5))
    except (subprocess.SubprocessError, ValueError, OSError):
        return {}


def serving_cell(response):
    match = re.search(r'\+QENG: ("servingcell"[^\r\n\']*)', response)
    if not match:
        return {}
    try:
        row = next(csv.reader([match[1]]))
        if len(row) < 17 or row[2] != 'LTE':
            return {}
        return dict(network=row[3] + ' LTE', cell_id=str(int(row[6], 16)),
                    cell=dict(mcc=int(row[4]), mnc=int(row[5]), lac=int(row[12], 16), cellid=int(row[6], 16)),
                    band=cellular_info.band_label(int(row[9]), int(row[8]) if row[8].isdigit() else None),
                    lac='Not applicable (LTE TAC: ' + str(int(row[12], 16)) + ')',
                    rsrp=str(float(row[13])) + ' dBm', rsrq=str(float(row[14])) + ' dB',
                    signal=str(float(row[15])) + ' dBm', sinr=str(float(row[16])) + ' dB')
    except (ValueError, IndexError, csv.Error):
        return {}


def collect(backend):
    result = dict.fromkeys(FIELDS)
    device = backend.values('network')['wan']['device']
    modem = query('-m', device).get('modem', {})
    generic, gpp = modem.get('generic', {}), modem.get('3gpp', {})
    result.update(model=clean(generic.get('model')), status=clean(generic.get('state')),
                  operator=clean(gpp.get('operator-name')), selection=clean(gpp.get('operator-name')),
                  imei=clean(gpp.get('imei')), revision=clean(generic.get('revision')))
    technologies = generic.get('access-technologies', [])
    result['network'] = ', '.join(technologies).upper() or None
    quality = generic.get('signal-quality', {}).get('value')
    if clean(quality) is not None:
        result['signal'] = str(quality) + '%'
    sim_path = clean(generic.get('sim'))
    if sim_path and sim_path != '/':
        sim = query('-i', sim_path).get('sim', {}).get('properties', {})
        result.update(iccid=clean(sim.get('iccid')), imsi=clean(sim.get('imsi')))
        lock = generic.get('unlock-required')
        result['sim_status'] = ('ready' if lock in ('none', '--', 'sim-pin2', 'sim-puk2')
                                and sim.get('active') == 'yes' else clean(lock) or 'unavailable')
    else:
        result['sim_status'] = 'Not present / unavailable'
    for path in generic.get('bearers', []):
        bearer = query('-b', path).get('bearer', {})
        if bearer.get('status', {}).get('connected') != 'yes':
            continue
        ipv4 = bearer.get('ipv4-config', {})
        result['ip'] = clean(ipv4.get('address'))
        result['dns'] = ', '.join(ipv4.get('dns', [])) or None
        result['uptime'] = clean(bearer.get('stats', {}).get('duration'))
        break
    location = query('-m', device, '--location-get').get('modem', {}).get('location', {}).get('3gpp', {})
    for key, source in [('cell_id', 'cid'), ('lac', 'lac')]:
        try:
            value = location.get(source, '--')
            if value.upper() not in ('--', 'FFFE', 'FFFF'):
                result[key] = str(int(value, 16))
        except (ValueError, AttributeError):
            pass
    try:
        response = backend.send_at({'command': 'AT+QENG="servingcell"'})
        if response.get('ok'):
            result.update(serving_cell(response.get('response', '')))
    except (RuntimeError, ValueError, OSError):
        pass
    return result


def locate(backend):
    """Resolve the current LTE cell on demand, without sending SIM identifiers."""
    cell = collect(backend).get('cell')
    if not cell or not (100 <= cell['mcc'] <= 999 and 0 <= cell['mnc'] <= 999
                        and 0 <= cell['lac'] <= 65535 and 0 < cell['cellid'] <= 0xfffffff):
        raise ValueError('Serving cell information is unavailable. Connect to an LTE network and try again.')
    endpoint = 'https://api.mylnikov.org/geolocation/cell?' + urlencode(dict(cell, v='1.1', data='open'))
    try:
        with urlopen(endpoint, timeout=7) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('Response too large')
        body = json.loads(raw)
        if body.get('result') != 200:
            raise ValueError('Cell not found')
        lat, lon = float(body['data']['lat']), float(body['data']['lon'])
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90
                and -180 <= lon <= 180 and (lat != 0 or lon != 0)):
            raise ValueError('Invalid coordinates')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError('Cell location was not found. Check the Internet connection or try again later; this cell may not be in the location database.') from None
    return dict(latitude=lat, longitude=lon, source='Mylnikov Geo-Location')
