"""IRMS MQTT Protocol V1.2 routing; independent of MQTT library and hardware."""
import json
import re
import time

FIELDS = {
    'BASE': 'devsn softver hardver mem_use cpu_use longitude latitude nettype cursim failover-current failover-primary failover-backup',
    'SIM1': 'csq nettype lac ci sid bid nid ip iccid imsi imei netband rsrp rsrq rssi sinr flowtx flowrx operator uptimes offtime module_version snr',
    'WAN': 'status mode ip flowtx flowrx wan1',
    'LAN': 'status ip lan1 lan2 lan3 lan4',
    'WLAN': 'status mode ip channel number',
    'NET_QUALITY': 'delay loss_rate jitter',
}
FIELDS['SIM2'] = FIELDS['SIM1']
TELEMETRY = (*FIELDS, 'HEARTBEAT', 'CLIENT_LIST', 'GPS', 'TRAFFIC')
MAX_PAYLOAD = 131072


def object_payload(raw):
    if len(raw) > MAX_PAYLOAD:
        raise ValueError('Payload too large')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    return data


def unhex(value):
    if not isinstance(value, str) or len(value) > MAX_PAYLOAD or not re.fullmatch(r'(?:[0-9a-fA-F]{2})*', value):
        raise ValueError('Expected an even-length hexadecimal string')
    return bytes.fromhex(value)


class Protocol:
    def __init__(self, serial, adapter, publish):
        if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', serial):
            raise ValueError('Invalid device serial number')
        self.serial, self.adapter, self.publish = serial, adapter, publish
        self.logged_in = False
        self.last = {}

    def send(self, suffix, data=None):
        return self.publish('/TX/' + self.serial + '/' + suffix,
                            b'' if data is None else json.dumps(data, separators=(',', ':'), allow_nan=False).encode())

    def telemetry(self, name):
        data = self.adapter.telemetry(name)
        # An absent modem must not overwrite the server's active SIM signal.
        if name in ('SIM1', 'SIM2') and not data:
            return
        if name in FIELDS:
            # The protocol requires strings, including counters and percentages.
            data = {key: '' if data.get(key) is None else str(data.get(key, ''))
                    for key in FIELDS[name].split()}
        self.send('DEVINFO/' + name, data)

    def receive(self, topic, raw, retained=False):
        prefix = '/RX/' + self.serial + '/'
        if not topic.startswith(prefix) or retained:
            return
        suffix = topic[len(prefix):]
        try:
            if suffix.startswith('PROXY/'):
                if self.logged_in:
                    self.adapter.proxies.receive(suffix, raw)
                return
            data = object_payload(raw)
            if suffix == 'LOGIN':
                if not isinstance(data.get('login'), str) or not data['login'].isdigit():
                    raise ValueError('Invalid login acknowledgement')
                self.logged_in = True
                self.last.clear()
                return
            if not self.logged_in:
                return
            if suffix in ('ALARM', 'GPSTRACKING', 'EVENT/GPSTRACKING'):
                identifier = data.get('id')
                if type(identifier) is not int or not 1 <= identifier <= 65535:
                    raise ValueError('Invalid acknowledgement id')
                self.adapter.ack('ALARM' if suffix == 'ALARM' else 'EVENT/GPSTRACKING', identifier)
            elif suffix in ('EVENT/LOGINFO', 'CONFIG') and ('time' in data or data.get('diff') == 'succeed'):
                return
            elif suffix.startswith('DEVINFO/') and suffix[8:] in TELEMETRY:
                if set(data) != {'get'}:
                    raise ValueError('Expected get request')
                self.telemetry(suffix[8:])
            elif suffix == 'INDUSTRY/GET':
                groups = data.get('get')
                if not isinstance(groups, list) or not groups or any(g not in ('gpio', 'serial') for g in groups):
                    raise ValueError('Expected gpio/serial list')
                result = self.adapter.operation(suffix, data)
                self.send(suffix, {key: result.get(key, {}) for key in groups})
            elif suffix in ('CONFIG', 'EVENT/GETFILE', 'EVENT/SETFILE', 'INDUSTRY/SET',
                            'EVENT/SHELL', 'EVENT/GETPATCH', 'UPGRADE', 'EVENT/UPGRADE'):
                if suffix == 'CONFIG':
                    data = {'cli': unhex(data.get('cli')).decode('utf-8')}
                elif suffix == 'EVENT/SETFILE':
                    data = dict(data, data=unhex(data.get('data')))
                result = self.adapter.operation(suffix, data)
                self.send(suffix, result)
        except (ValueError, KeyError, TypeError, UnicodeError, OSError, RuntimeError) as error:
            if suffix.startswith('PROXY/'):
                return
            if suffix in TELEMETRY:
                return
            self.send(suffix, dict(result='fail', error=str(error)[:200]))

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.logged_in:
            if now - self.last.get('LOGIN', -1e9) >= 30:
                self.send('LOGIN')
                self.last['LOGIN'] = now
            return
        for suffix, raw in self.adapter.proxies.poll():
            self.publish('/TX/' + self.serial + '/' + suffix, raw)
        for name in TELEMETRY:
            interval = 180 if name == 'HEARTBEAT' else 60 if name == 'GPS' else 180
            if now - self.last.get(name, -1e9) >= interval:
                self.telemetry(name)
                self.last[name] = now
        if now - self.last.get('INDUSTRY', -1e9) >= 3600:
            self.send('INDUSTRY/GET', self.adapter.operation('INDUSTRY/GET', {'get': ['gpio', 'serial']}))
            self.last['INDUSTRY'] = now
        for suffix, data in self.adapter.events():
            self.send(suffix, data)
