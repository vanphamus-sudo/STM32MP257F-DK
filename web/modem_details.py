"""Read-only LTE status. Identifiers are returned only through the authenticated API."""
import csv
import json
import re
import subprocess

FIELDS = ('selection', 'model', 'uptime', 'status', 'network', 'signal', 'ip', 'dns',
          'sim_status', 'iccid', 'imsi', 'imei', 'lac', 'cell_id', 'rsrp', 'rsrq',
          'sinr', 'operator', 'band', 'revision')


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
                    band='LTE BAND ' + str(int(row[9])),
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
