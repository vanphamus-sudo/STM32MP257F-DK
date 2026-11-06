"""OpenWrt telemetry and explicitly configured IRMS operation adapters."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import version_info
import mqtt_metrics
import traffic_stats
from mqtt_proxy import Proxies


def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def query(*args):
    try:
        return json.loads(subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=10))
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.new')
    with temporary.open('w', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump(data, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class RouterData:
    def __init__(self, config, state=Path('/etc/router-web/mqtt-state')):
        self.config, self.state = config, state
        self.proxies = Proxies(config)
        self.counters = {}
        self.flow_path = state / 'flow-periods.json'
        if state == Path('/etc/router-web/mqtt-state'):
            try:
                self.flow_path = traffic_stats.state_path().parent / 'mqtt-periods.json'
            except (OSError, ValueError, RuntimeError):
                pass
        self.periods = json.loads(read(self.flow_path, '{}'))
        self.cpu = None
        try:
            ticks = [int(value) for value in read('/proc/stat').splitlines()[0].split()[1:]]
            self.cpu = sum(ticks[:8]), ticks[3] + ticks[4]
        except (ValueError, IndexError):
            pass
        self.cache = {}
        self.cache_until = 0
        self.last_events = 0
        self.last_vpn = None
        self.last_quality = 0
        self.quality_cache = {}
        self.pending = json.loads(read(state / 'pending.json', '{}'))

    def interface(self, name):
        return query('ubus', 'call', 'network.interface.' + name, 'status')

    def flow(self, device, topic):
        if not device or '/' in device:
            return '', ''
        measured = traffic_stats.current()
        item = measured.get('roles', {}).get(topic.lower(), {})
        if item.get('available') and item.get('device') == device and measured.get('stale_seconds', 999) <= 20:
            key = self.config['serial'] + '/' + topic
            previous = self.periods.get(key, {})
            totals = {direction: item['total_' + direction + '_bytes'] for direction in ('tx', 'rx')}
            result = tuple(str(round((totals[direction] - previous.get(direction, 0)
                                      if totals[direction] >= previous.get(direction, 0) else totals[direction]) / 1024, 3))
                           for direction in ('tx', 'rx'))
            self.periods[key] = totals
            atomic_json(self.flow_path, self.periods)
            return result
        result = []
        for direction in ('tx', 'rx'):
            value = read('/sys/class/net/' + device + '/statistics/' + direction + '_bytes')
            if not value.isdigit():
                result.append('')
                continue
            current = int(value)
            key = topic, device, direction
            previous = self.counters.get(key, 0)
            self.counters[key] = current
            result.append(str(round((current - previous if current >= previous else current) / 1024, 3)))
        return tuple(result)

    def snapshot(self):
        if time.monotonic() < self.cache_until:
            return self.cache
        wan, lan, wlan = [self.interface(name) for name in ('wan', 'lan', 'hotspot')]
        listing = query('mmcli', '-L', '-J').get('modem-list', [])
        modem = query('mmcli', '-m', listing[0], '-J').get('modem', {}) if listing else {}
        generic = modem.get('generic', {})
        sim = query('mmcli', '-i', generic['sim'], '-J').get('sim', {}).get('properties', {}) if generic.get('sim') not in (None, '/', '--') else {}
        if listing:
            modem.update(query('mmcli', '-m', listing[0], '--signal-get', '-J').get('modem', {}))
        locations = query('mmcli', '-m', listing[0], '--location-get', '-J').get('modem', {}).get('location', {}) if listing else {}
        location = locations.get('3gpp', {})
        bearer = {}
        for path in generic.get('bearers', []):
            candidate = query('mmcli', '-b', path, '-J').get('bearer', {})
            if candidate.get('status', {}).get('connected') == 'yes':
                bearer = candidate
                break
        radio = {}
        if listing:
            import openwrt_backend
            radio = mqtt_metrics.radio(openwrt_backend)
        self.cache = dict(wan=wan, lan=lan, wlan=wlan, modem=modem, sim=sim, location=location,
                          locations=locations, bearer=bearer, radio=radio)
        self.cache_until = time.monotonic() + 20
        return self.cache

    @staticmethod
    def ip(interface):
        addresses = interface.get('ipv4-address', [])
        return addresses[0].get('address', '') if addresses else ''

    @staticmethod
    def link(device):
        if not device or '/' in device:
            return 'down'
        base = '/sys/class/net/' + device + '/'
        if read(base + 'carrier') != '1':
            return 'down'
        speed, duplex = read(base + 'speed'), read(base + 'duplex')
        return 'up' + ('/' + speed + 'Mbps/' + duplex + '-duplex' if speed.isdigit() and duplex else '')

    def telemetry(self, name):
        if name == 'TRAFFIC':
            return traffic_stats.current()
        if name == 'HEARTBEAT':
            return dict(power_time=int(float(read('/proc/uptime', '0').split()[0])))
        if name == 'GPS':
            # A GPS provider writes a complete V1.2 object here; absence is not a fabricated fix.
            path = self.config.get('gps_file')
            value = json.loads(read(path, '{}')) if path else mqtt_metrics.gps(self.snapshot()['locations'])
            if not isinstance(value, dict):
                raise ValueError('GPS provider must return a JSON object')
            return value
        if name == 'NET_QUALITY':
            path = self.config.get('network_quality_file')
            if path:
                value = json.loads(read(path, '{}'))
            else:
                if time.monotonic() - self.last_quality >= 60 or not self.last_quality:
                    self.quality_cache = mqtt_metrics.quality(self.snapshot()['wan'].get('l3_device'), self.config.get('quality_target', '1.1.1.1'))
                    self.last_quality = time.monotonic()
                value = self.quality_cache
            if not isinstance(value, dict):
                raise ValueError('Network quality provider must return a JSON object')
            return value
        data = self.snapshot()
        wan, lan, wlan, modem, sim = [data[key] for key in ('wan', 'lan', 'wlan', 'modem', 'sim')]
        generic, gpp = modem.get('generic', {}), modem.get('3gpp', {})
        if name == 'BASE':
            memory = {}
            for line in read('/proc/meminfo').splitlines():
                key, value = line.split(':', 1)
                memory[key] = int(value.split()[0])
            usage = ''
            if memory.get('MemTotal'):
                usage = str(round(100 * (1 - memory.get('MemAvailable', memory.get('MemFree', 0)) / memory['MemTotal']), 1)) + '%'
            cpu_usage = ''
            line = read('/proc/stat').splitlines()
            if line:
                ticks = [int(value) for value in line[0].split()[1:]]
                current = sum(ticks[:8]), ticks[3] + ticks[4]
                if self.cpu and current[0] > self.cpu[0]:
                    cpu_usage = str(round(100 * (1 - (current[1] - self.cpu[1]) / (current[0] - self.cpu[0])), 1)) + '%'
                self.cpu = current
            device = wan.get('l3_device', '')
            gps = self.telemetry('GPS')
            current_sim = 'sim2' if str(generic.get('primary-sim-slot')) == '2' else 'sim1'
            is_modem_wan = wan.get('proto') == 'modemmanager' or device == data['bearer'].get('status', {}).get('interface')
            network = self.nettype(generic) if is_modem_wan else 'WLAN' if device.startswith(('wlan', 'phy')) else 'WAN' if device else ''
            return dict(devsn=self.config['serial'], softver=version_info.VERSION,
                        hardver=self.config.get('hardware_version', 'STM32MP257F-DK'),
                        mem_use=usage, cpu_use=cpu_usage, cursim=current_sim if sim else '',
                        longitude=gps.get('lng', ''), latitude=gps.get('lat', ''),
                        nettype=network, **{'failover-current': device,
                        'failover-primary': self.config.get('primary_interface') or device,
                        'failover-backup': self.config.get('backup_interface', '')})
        if name in ('SIM1', 'SIM2'):
            active_sim = 'SIM2' if str(generic.get('primary-sim-slot')) == '2' else 'SIM1'
            if name != active_sim or not sim:
                return {}
            modem_device = data['bearer'].get('status', {}).get('interface', '')
            tx, rx = self.flow(modem_device, name)
            signal = modem.get('signal', {})
            lte = signal.get('lte', {})
            result = dict(nettype=self.nettype(generic), ip=mqtt_metrics.clean(data['bearer'].get('ipv4-config', {}).get('address')),
                          iccid=sim.get('iccid', ''), imsi=sim.get('imsi', ''), imei=gpp.get('imei', ''),
                          operator=gpp.get('operator-name', ''), module_version=generic.get('revision', ''),
                          flowtx=tx, flowrx=rx)
            result['uptimes'] = mqtt_metrics.clean(data['bearer'].get('stats', {}).get('duration'))
            result['offtime'] = '0' if data['bearer'].get('status', {}).get('connected') == 'yes' else ''
            for field, source in (('lac', 'lac'), ('ci', 'cid')):
                value = data['location'].get(source, '')
                if field == 'lac' and str(value).upper() in ('FFFE', 'FFFF', '--', ''):
                    value = data['location'].get('tac', '')
                try:
                    result[field] = str(int(value, 16)) if value and value != '--' else ''
                except ValueError:
                    result[field] = ''
            for key in ('rsrp', 'rsrq', 'rssi', 'sinr', 'snr'):
                result[key] = mqtt_metrics.clean(lte.get(key))
            result.update(data['radio'])
            return result
        if name in ('WAN', 'LAN', 'WLAN'):
            interface = dict(WAN=wan, LAN=lan, WLAN=wlan)[name]
            result = dict(status='1' if interface.get('up') else '0', ip=self.ip(interface))
            if name == 'WAN':
                tx, rx = self.flow(interface.get('l3_device', ''), name)
                result.update(mode=interface.get('proto', ''), flowtx=tx, flowrx=rx,
                              wan1='up' if interface.get('proto') == 'modemmanager' and interface.get('up') else self.link(interface.get('device') or interface.get('l3_device', '')))
            elif name == 'LAN':
                ports = self.config.get('lan_ports', [])
                if not ports:
                    bridge = Path('/sys/class/net') / interface.get('device', 'br-lan') / 'brif'
                    ports = sorted(path.name for path in bridge.iterdir()) if bridge.is_dir() else []
                result.update({f'lan{i+1}': self.link(ports[i]) if i < len(ports) else '' for i in range(4)})
            else:
                wireless = query('ubus', 'call', 'network.wireless', 'status')
                for radio in wireless.values():
                    for entry in radio.get('interfaces', []):
                        if entry.get('section') == 'router_ap':
                            settings = entry.get('config', {})
                            clients = query('ubus', 'call', 'hostapd.' + entry.get('ifname', ''), 'get_clients')
                            result.update(mode=settings.get('mode', ''), channel=mqtt_metrics.channel(entry.get('ifname', '')) or radio.get('config', {}).get('channel', ''),
                                          number=str(len(clients.get('clients', {}))))
            return result
        if name == 'CLIENT_LIST':
            clients = []
            for line in read('/tmp/dhcp.leases').splitlines():
                fields = line.split()
                if len(fields) >= 4 and (fields[0] == '0' or int(fields[0]) > time.time()):
                    clients.append(dict(ip=fields[2], mac=fields[1], tport=[], uport=[]))
            return dict(client=clients)
        raise ValueError('Unknown telemetry')

    @staticmethod
    def nettype(generic):
        technologies = ' '.join(generic.get('access-technologies', [])).lower()
        for needle, label in [('5g', '5G'), ('lte', '4G'), ('umts', '3G'), ('hspa', '3G'), ('gsm', '2G'), ('edge', '2G')]:
            if needle in technologies:
                return label
        return ''

    def operation(self, name, data):
        if name in ('UPGRADE', 'EVENT/UPGRADE'):
            import firmware_update
            return firmware_update.submit(data, topic=name)
        if name == 'EVENT/GETPATCH':
            return {'avilable': str(shutil.disk_usage('/').free // 1024)}
        if name == 'INDUSTRY/GET' and name not in self.config.get('handlers', {}):
            serial = {}
            settings = json.loads(read('/etc/router-web/serial-tcp.json', '{}'))
            if settings:
                services = query('ubus', 'call', 'service', 'list', json.dumps({'name': 'router-serial'}))
                running = any(item.get('running') for item in services.get('router-serial', {}).get('instances', {}).values())
                serial['serial1'] = dict(name='serial1', status=int(running),
                                         type=self.config.get('serial_type', 'RS232'), rate=settings.get('baud', 9600),
                                         parity='none', databits=8, stopbits=1)
            return dict(gpio={}, serial=serial)
        # Administrator-installed executables translate vendor CLI/config and board-specific I/O.
        # Broker content is stdin data, never an executable or shell command.
        executable = self.config.get('handlers', {}).get(name)
        if not executable:
            raise ValueError('Operation is unavailable on this device: ' + name)
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            raise ValueError('Handler must be an absolute executable path')
        wire = dict(data)
        if isinstance(wire.get('data'), bytes):
            wire['data'] = wire['data'].hex()
        try:
            result = subprocess.run([executable], input=json.dumps(dict(operation=name, data=wire)),
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=30, check=True)
        except subprocess.SubprocessError as error:
            raise RuntimeError('Device operation handler failed') from error
        if len(result.stdout) > 131072:
            raise ValueError('Handler response too large')
        response = json.loads(result.stdout)
        if not isinstance(response, dict):
            raise ValueError('Handler must return a JSON object')
        return response

    def ack(self, suffix, identifier):
        key = suffix + ':' + str(identifier)
        if key in self.pending:
            del self.pending[key]
            atomic_json(self.state / 'pending.json', self.pending)

    def events(self):
        if time.monotonic() - self.last_events < 30:
            return []
        self.last_events = time.monotonic()
        # Local producers atomically enqueue JSON {topic, data}; alarm/GPS ids persist until application ACK.
        queue = self.state / 'outbox'
        queue.mkdir(parents=True, exist_ok=True, mode=0o700)
        outgoing = []
        try:
            import openwrt_backend
            import openvpn_client
            vpn = openvpn_client.status(openwrt_backend)
            current = (vpn.get('state') == 'connected', vpn.get('local_ip', ''))
            if vpn.get('available') and current != self.last_vpn:
                self.last_vpn = current
                outgoing.append(('SDWAN/VPNSTATUS', dict(type='openvpn', status='1' if current[0] else '0', ip=current[1], mac='')))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
        for path in sorted(queue.glob('*.json'))[:100]:
            try:
                event = json.loads(path.read_text())
                suffix, data = event['topic'], event['data']
                if suffix not in ('ALARM', 'EVENT/GPSTRACKING', 'EVENT/LOGINFO', 'CONFIG', 'INDUSTRY/UPLOAD', 'SDWAN/VPNSTATUS', 'UPGRADE', 'EVENT/UPGRADE') or not isinstance(data, dict):
                    raise ValueError('Invalid outbox event')
                if suffix in ('ALARM', 'EVENT/GPSTRACKING'):
                    identifier = data.get('id')
                    if type(identifier) is not int or not 1 <= identifier <= 65535:
                        raise ValueError('Invalid event id')
                    if len(self.pending) >= 1000:
                        break
                    self.pending[suffix + ':' + str(identifier)] = event
                    atomic_json(self.state / 'pending.json', self.pending)
                else:
                    outgoing.append((suffix, data))
                path.unlink()
            except (ValueError, KeyError, TypeError):
                path.rename(path.with_suffix('.invalid'))
        outgoing.extend((event['topic'], event['data']) for event in self.pending.values())
        return outgoing
