"""Read-only live radio, CPU, network quality and GPS helpers."""
import csv
import json
import math
from pathlib import Path
import re
import subprocess
import time


def clean(value):
    return '' if value is None or str(value) in ('--', '-', 'unknown', '') else str(value)


def radio(backend):
    result = {}
    try:
        csq = backend.send_at({'command': 'AT+CSQ'})
        match = re.search(r'\+CSQ:\s*(\d+),', csq.get('response', ''))
        if csq.get('ok') and match and 0 <= int(match[1]) <= 31:
            result['csq'] = match[1]
        cell = backend.send_at({'command': 'AT+QENG="servingcell"'})
        match = re.search(r'\+QENG:\s*("servingcell"[^\r\n\']*)', cell.get('response', ''))
        if cell.get('ok') and match:
            row = next(csv.reader([match[1]]))
            if len(row) >= 17 and row[2] == 'LTE':
                result.update(nettype='4G', ci=str(int(row[6], 16)), lac=str(int(row[12], 16)),
                              netband='band' + row[9], rsrp=clean(row[13]), rsrq=clean(row[14]),
                              rssi=clean(row[15]), sinr=clean(row[16]))
    except (OSError, ValueError, RuntimeError, IndexError, csv.Error):
        pass
    return result


def quality(device, target='1.1.1.1'):
    if not device or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', device):
        return {}
    try:
        result = subprocess.run(['ping', '-n', '-I', device, '-c', '3', '-W', '1', '-w', '5', target],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=7)
    except (OSError, subprocess.SubprocessError):
        return {}
    loss = re.search(r'([\d.]+)% packet loss', result.stdout)
    samples = [float(value) for value in re.findall(r'time[=<]([\d.]+)\s*ms', result.stdout)]
    value = dict(loss_rate=loss[1] + '%' if loss else '')
    if samples:
        value['delay'] = f'{sum(samples)/len(samples):.3f}ms'
        if len(samples) > 1:
            value['jitter'] = f'{sum(abs(b-a) for a,b in zip(samples,samples[1:]))/(len(samples)-1):.3f}ms'
    return value


def gps(location):
    raw = location.get('gps', {})
    try:
        lat, lng = float(raw.get('latitude')), float(raw.get('longitude'))
        if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
            return {}
        result = dict(fix=clean(raw.get('utc')), lat=lat, lng=lng)
        altitude = clean(raw.get('altitude'))
        if altitude and math.isfinite(float(altitude)):
            result['height'] = float(altitude)
        return result
    except (TypeError, ValueError):
        return {}


def channel(device):
    try:
        output = subprocess.check_output(['iw', 'dev', device, 'info'], text=True, stderr=subprocess.DEVNULL, timeout=3)
        match = re.search(r'\bchannel (\d+)\b', output)
        return match[1] if match else ''
    except (OSError, subprocess.SubprocessError):
        return ''
