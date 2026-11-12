"""USER1/LD9 recovery controller for STM32MP257F-DK (Linux only)."""
import argparse
try:
    import fcntl
except ImportError:  # Allow configuration-plan tests on Windows.
    fcntl = None
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import usb_tethering

KEY = 0x101  # BTN_1, USER1 / B5 / PC5
HOLD = 8.0
LOG = logging.getLogger('router-button')


def gesture(seconds):
    if seconds < .15:
        return None
    return 'recover' if seconds >= HOLD else 'reboot'


def plans(network, dhcp, firewall):
    """Restore dedicated Ethernet LAN and USB management access."""
    ports = network.get('lan_bridge', {}).get('ports', [])
    ports = [ports] if isinstance(ports, str) else ports
    device = network.get('router_ethernet', {}).get('device')
    if not device and len(ports) == 1:
        device = ports[0].split('.')[0]
    if not device or not re.fullmatch(r'[A-Za-z0-9_-]{1,10}', device):
        raise RuntimeError('Cannot identify dedicated Ethernet port; refusing to guess')
    if network.get('lan_bridge', {}).get('name') != 'br-lan':
        raise RuntimeError('Dedicated br-lan is missing')
    if firewall.get('lan', {}).get('name') != 'lan' or firewall.get('wan', {}).get('name') != 'wan':
        raise RuntimeError('Dedicated LAN/WAN firewall zones are missing')
    if 'router_dns' not in dhcp:
        raise RuntimeError('Dedicated DHCP server is missing')
    edits = {p: [] for p in ('network', 'dhcp', 'firewall')}

    def set_(p, key, value):
        edits[p].append(('set', p + '.' + key, value))

    def delete(p, key):
        edits[p].append(('delete', p + '.' + key, None))

    def list_(p, key, values):
        for value in values:
            edits[p].append(('add_list', p + '.' + key, value))

    set_('network', 'router_ethernet', 'router_ethernet')
    for k, v in dict(device=device, mode='lan', lan_vlan='10', wan_vlan='20').items():
        set_('network', 'router_ethernet.' + k, v)
    if ports:
        delete('network', 'lan_bridge.ports')
    list_('network', 'lan_bridge.ports', [device])
    set_('network', 'lan_bridge.bridge_empty', '1')
    if 'ethernet_wan' in network:
        delete('network', 'ethernet_wan')
    if 'rf_passthrough' in network:
        delete('network', 'rf_passthrough')
        set_('firewall', 'wan.masq', '1')
        for name in ('rf_passthrough', 'rf_pass_out', 'rf_pass_in', 'rf_pass_dhcp'):
            if name in firewall:
                delete('firewall', name)
    set_('network', 'lan', 'interface')
    for k, v in dict(device='br-lan', proto='static', ipaddr='192.168.10.1', netmask='255.255.255.0').items():
        set_('network', 'lan.' + k, v)
    for key in ('gateway', 'ip6assign', 'ip6addr'):
        if key in network.get('lan', {}):
            delete('network', 'lan.' + key)
    set_('dhcp', 'lan', 'dhcp')
    for k, v in dict(interface='lan', ignore='0', start='50', limit='151', leasetime='12h', dhcpv6='disabled', ra='disabled', ndp='disabled').items():
        set_('dhcp', 'lan.' + k, v)
    if 'dhcp_option' in dhcp.get('lan', {}):
        delete('dhcp', 'lan.dhcp_option')
    interfaces = dhcp['router_dns'].get('interface', [])
    interfaces = interfaces.split() if isinstance(interfaces, str) else interfaces
    if interfaces and 'lan' not in interfaces:
        list_('dhcp', 'router_dns.interface', ['lan'])
    excluded = dhcp['router_dns'].get('notinterface', [])
    excluded = excluded.split() if isinstance(excluded, str) else excluded
    if 'lan' in excluded:
        delete('dhcp', 'router_dns.notinterface')
        list_('dhcp', 'router_dns.notinterface', [x for x in excluded if x != 'lan'])
    set_('dhcp', 'router_dns.port', '53')
    for zone in ('lan', 'wan'):
        members = firewall[zone].get('network', [])
        members = members.split() if isinstance(members, str) else members
        if members:
            delete('firewall', zone + '.network')
        members = [n for n in members if n != 'ethernet_wan']
        if zone == 'lan' and 'lan' not in members:
            members.append('lan')
        list_('firewall', zone + '.network', members)
    for name, options in {
        'lan_dhcp': dict(proto='udp', src_port='68', dest_port='67'),
        'lan_dns': dict(proto='tcp udp', dest_port='53'),
        'lan_web': dict(proto='tcp', dest_ip='192.168.10.1', dest_port='8081'),
        'lan_admin': dict(proto='tcp', dest_port='22 80 443'),
        'lan_ping': dict(proto='icmp'),
    }.items():
        if name in firewall:
            delete('firewall', name)
        set_('firewall', name, 'rule')
        for k, v in (dict(name='Recovery ' + name, src='lan', family='ipv4', target='ACCEPT') | options).items():
            set_('firewall', name + '.' + k, v)
    usb_edits = usb_tethering.recovery_plans(network, dhcp, firewall)
    # Rebuild DNS inclusion/exclusion once for both recovery interfaces.
    edits['dhcp'] = [op for op in edits['dhcp']
                     if op[1] not in ('dhcp.router_dns.interface', 'dhcp.router_dns.notinterface')]
    usb_edits['dhcp'] = [op for op in usb_edits['dhcp']
                         if op[1] not in ('dhcp.router_dns.interface', 'dhcp.router_dns.notinterface')]
    if interfaces:
        delete('dhcp', 'router_dns.interface')
        list_('dhcp', 'router_dns.interface', list(dict.fromkeys(interfaces + ['lan', 'management'])))
    if excluded:
        delete('dhcp', 'router_dns.notinterface')
        list_('dhcp', 'router_dns.notinterface', [x for x in excluded if x not in ('lan', 'management')])
    for package in edits:
        edits[package].extend(usb_edits[package])
    return edits


def recover(platform, write):
    """Validate all candidates before publishing. Keep a durable rollback journal."""
    edits = plans(*(platform.values(p) for p in ('network', 'dhcp', 'firewall')))
    originals = {p: (platform.CONFIG / p).read_text() for p in edits}
    for p in edits:
        if platform.run('uci', 'changes', p):
            raise RuntimeError('Pending UCI changes: ' + p)
    with tempfile.TemporaryDirectory(prefix='router-recovery-') as tmp:
        stage = Path(tmp)
        (stage / 'delta').mkdir()
        for p, text in originals.items():
            write(stage / p, text)
        for p, operations in edits.items():
            for op, key, value in operations:
                platform.run('uci', '-c', tmp, '-t', str(stage / 'delta'), op,
                             key if value is None else key + '=' + str(value))
            platform.run('uci', '-c', tmp, '-t', str(stage / 'delta'), 'commit', p)
        for p, text in originals.items():
            if (platform.CONFIG / p).read_text() != text or platform.run('uci', 'changes', p):
                raise RuntimeError('Concurrent configuration edit: ' + p)
        backup = platform.STATE / ('button-recovery-' + str(time.time_ns()))
        backup.mkdir(mode=0o700)
        for p, text in originals.items():
            write(backup / p, text)
        journal = platform.STATE / 'button-recovery-pending.json'
        write(journal, json.dumps(originals))
        os.sync()
        try:
            for p in edits:
                write(platform.CONFIG / p, (stage / p).read_text())
            platform.run('fw4', 'check')
            write(platform.STATE / 'button-recovery-completed', '192.168.10.1\n')
            os.sync()
            journal.unlink()
            os.sync()
        except BaseException:
            for p, text in originals.items():
                write(platform.CONFIG / p, text)
            (platform.STATE / 'button-recovery-completed').unlink(missing_ok=True)
            os.sync()
            journal.unlink()
            raise
    LOG.warning('Ethernet LAN and USB management recovery saved; backup: %s', backup)


def restore_pending(platform, write):
    journal = platform.STATE / 'button-recovery-pending.json'
    if journal.exists():
        original = json.loads(journal.read_text())
        if set(original) != {'network', 'dhcp', 'firewall'}:
            raise RuntimeError('Invalid recovery journal')
        for p, text in original.items():
            write(platform.CONFIG / p, text)
        (platform.STATE / 'button-recovery-completed').unlink(missing_ok=True)
        os.sync()
        journal.unlink()
        os.sync()
        LOG.warning('Restored interrupted recovery transaction')


def discover():
    devices = []
    for entry in Path('/sys/class/input').glob('event*'):
        if (entry / 'device/name').read_text().strip() == 'gpio-keys':
            devices.append(Path('/dev/input') / entry.name)
    leds = [p for p in Path('/sys/class/leds').iterdir()
            if 'orange' in p.name and (p / 'brightness').exists()]
    if len(devices) != 1 or len(leds) != 1:
        raise RuntimeError('Expected one gpio-keys input and one orange LD9 LED')
    return devices[0], leds[0]


def key_down(fd):
    keys = bytearray(96)
    fcntl.ioctl(fd, 0x80000000 | (len(keys) << 16) | (ord('E') << 8) | 0x18, keys)
    return bool(keys[KEY // 8] & (1 << (KEY % 8)))


class Hardware:
    """Use evdev or OpenWrt's kernel button events; request PH6 via sysfs.

    The installed ST/OpenWrt image has neither evdev nor an LD9 DT node.
    GPIO numbers are resolved from controller labels, never hard-coded.
    """
    def __init__(self):
        self.input = None
        self.led = None
        self.exports = []
        self.events = None
        self.pressed = False
        try:
            devices = list(Path('/sys/class/input').glob('event*'))
            if devices:
                device, self.led = discover()
                self.input = device.open('rb', buffering=0)
                supported = bytearray(96)
                fcntl.ioctl(self.input.fileno(), 0x80000000 | (96 << 16) | (ord('E') << 8) | 0x21, supported)
                if not supported[KEY // 8] & (1 << (KEY % 8)):
                    raise RuntimeError('USER1 BTN_1 is not exposed')
                self.old_brightness = (self.led / 'brightness').read_text()
                self.old_trigger = re.search(r'\[([^]]+)\]', (self.led / 'trigger').read_text())[1]
                (self.led / 'trigger').write_text('none')
                self.maximum = (self.led / 'max_brightness').read_text().strip()
            else:
                node = Path('/sys/firmware/devicetree/base/gpio-keys/button-user-1')
                if int.from_bytes((node / 'linux,code').read_bytes(), 'big') != KEY:
                    raise RuntimeError('Unexpected USER1 device-tree key code')
                if not Path('/sys/bus/platform/drivers/gpio-keys/gpio-keys').exists():
                    raise RuntimeError('OpenWrt gpio-keys driver is not bound')
                self.events = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 15)
                self.events.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
                self.events.bind((os.getpid(), 1))
                self.events.setblocking(False)
                self.output = self.export('GPIOH', 6, 'low')
        except BaseException:
            self.close()
            raise

    def export(self, label, offset, direction):
        root = Path('/sys/class/gpio')
        chips = [p for p in root.glob('gpiochip*') if (p / 'label').read_text().strip() == label]
        if len(chips) != 1 or offset >= int((chips[0] / 'ngpio').read_text()):
            raise RuntimeError('Missing GPIO controller: ' + label)
        number = int((chips[0] / 'base').read_text()) + offset
        # EBUSY must fail: do not adopt a GPIO owned by another component.
        (root / 'export').write_text(str(number))
        self.exports.append(number)
        candidates = [root / ('gpio' + str(number)), root / ('P' + label.removeprefix('GPIO') + str(offset))]
        deadline = time.monotonic() + 2
        while not any((p / 'direction').exists() for p in candidates) and time.monotonic() < deadline:
            time.sleep(.02)
        pin = next(p for p in candidates if (p / 'direction').exists())
        (pin / 'direction').write_text(direction)
        return pin

    def down(self):
        if self.input:
            return key_down(self.input.fileno())
        while True:
            try:
                packet, sender = self.events.recvfrom(8192)
            except BlockingIOError:
                return self.pressed
            if sender[0] != 0:  # Only kernel uevents can request a reboot.
                continue
            fields = dict(item.split(b'=', 1) for item in packet.split(b'\0') if b'=' in item)
            if fields.get(b'SUBSYSTEM') == b'button' and fields.get(b'BUTTON') == b'BTN_1':
                action = fields.get(b'ACTION')
                if action in (b'pressed', b'released'):
                    self.pressed = action == b'pressed'

    def light(self, on):
        if self.led:
            (self.led / 'brightness').write_text(self.maximum if on else '0')
        else:
            (self.output / 'value').write_text('1' if on else '0')

    def close(self):
        if self.events:
            self.events.close()
        if self.input:
            self.input.close()
        if self.led and hasattr(self, 'old_trigger'):
            (self.led / 'brightness').write_text(self.old_brightness)
            (self.led / 'trigger').write_text(self.old_trigger)
        if hasattr(self, 'output'):
            (self.output / 'value').write_text('0')
        for number in reversed(self.exports):
            Path('/sys/class/gpio/unexport').write_text(str(number))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Request hardware, report state, then release it; no reboot or recovery')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    model = Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    if b'st,stm32mp257f-dk' not in model:
        raise RuntimeError('This default hardware profile requires STM32MP257F-DK')
    hardware = Hardware()
    try:
        if args.check:
            print(json.dumps(dict(button='USER1 PC5', led='LD9 PH6', pressed=hardware.down(), backend='evdev' if hardware.input else 'kernel-uevent/gpio-sysfs')))
            return
        import openwrt_backend as platform
        import firmware_update
        from server import atomic_write
        platform.STATE.mkdir(mode=0o700, exist_ok=True)
        with (platform.STATE / 'button.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            restore_pending(platform, atomic_write)
            signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit()))
            started = None
            armed = not hardware.down()
            completion = platform.STATE / 'button-recovery-completed'
            completion_checked = 0
            LOG.info('USER1 ready: short release=reboot, hold 8s then release=LAN/USB recovery; LD9=PH6')
            try:
                while True:
                    now = time.monotonic()
                    down = hardware.down()
                    if started is None and not down and completion.exists() and now - completion_checked > 1:
                        completion_checked = now
                        result = subprocess.run(['ip', '-4', 'addr', 'show', 'dev', 'br-lan'], capture_output=True, text=True, timeout=5)
                        usb_device = platform.values('network').get('management', {}).get('device', 'usb0')
                        usb_result = subprocess.run(['ip', '-4', 'addr', 'show', 'dev', usb_device], capture_output=True, text=True, timeout=5)
                        if (result.returncode == 0 and 'inet 192.168.10.1/24 ' in result.stdout
                                and usb_result.returncode == 0 and 'inet 192.168.7.1/24 ' in usb_result.stdout):
                            for _ in range(3):
                                hardware.light(True)
                                time.sleep(.2)
                                hardware.light(False)
                                time.sleep(.2)
                            completion.unlink()
                            os.sync()
                    if not armed:
                        armed = not down  # Ignore a button held during service startup.
                    elif down:
                        if started is None:
                            started = now
                        elapsed = now - started
                        on = elapsed >= HOLD or int(elapsed * 4) % 2 == 0
                        hardware.light(on)
                    elif started is not None:
                        action = gesture(now - started)
                        started = None
                        if action:
                            LOG.warning('USER1 requested %s', action)
                            try:
                                with firmware_update.locked():
                                    if action == 'recover':
                                        subprocess.run(['/etc/init.d/router-web', 'stop'], check=True, timeout=30)
                                        try:
                                            recover(platform, atomic_write)
                                        except BaseException:
                                            subprocess.run(['/etc/init.d/router-web', 'start'], timeout=30)
                                            raise
                                    hardware.light(True)
                                    os.sync()
                                    subprocess.run(['reboot'], check=True, timeout=30)
                                    return
                            except Exception:
                                LOG.exception('Button action failed; no reboot requested')
                                for _ in range(5):
                                    hardware.light(True)
                                    time.sleep(.1)
                                    hardware.light(False)
                                    time.sleep(.1)
                    else:
                        hardware.light(False)
                    time.sleep(.05)
            finally:
                hardware.light(False)
    finally:
        hardware.close()


if __name__ == '__main__':
    main()
