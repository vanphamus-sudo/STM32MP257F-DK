"""Generate/install the dedicated router configuration on a fresh OpenWrt board.

Default: write candidates only. --install backs up and writes configuration for
the next reboot; it does not restart networking under an active SSH session.
"""
import argparse
from pathlib import Path
import re
import secrets
import shutil

from server import atomic_write
from openwrt_backend import run
from initialize import initialize


def section(kind, section_name, **options):
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'
    text = f'config {kind} {quote(section_name)}\n'
    for key, value in options.items():
        items = value if isinstance(value, list) else [value]
        for item in items:
            text += f"\t{'list' if isinstance(value, list) else 'option'} {key} {quote(item)}\n"
    return text + '\n'


def configs(lan, modem, usb=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', lan) or (usb and not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', usb)):
        raise ValueError('Use actual Linux Ethernet/USB interface names.')
    if lan == usb:
        raise ValueError('LAN and USB management must use different devices.')
    if not re.fullmatch(r'/sys/devices/[A-Za-z0-9_./:@+-]+', modem) or '..' in modem.split('/'):
        raise ValueError('Use the modem.generic.device sysfs path from mmcli, not /dev/cdc-wdm0.')
    network = section('interface', 'loopback', device='lo', proto='static', ipaddr='127.0.0.1', netmask='255.0.0.0')
    network += section('device', 'lan_bridge', name='br-lan', type='bridge', ports=[lan])
    network += section('interface', 'lan', device='br-lan', proto='static', ipaddr='192.168.10.1', netmask='255.255.255.0')
    network += section('device', 'wifi_bridge', name='br-hotspot', type='bridge', bridge_empty='1')
    network += section('interface', 'hotspot', device='br-hotspot', proto='static', ipaddr='192.168.20.1', netmask='255.255.255.0')
    network += section('interface', 'wan', proto='modemmanager', device=modem, apn='telstra.extranet',
                       iptype='ipv4', allow_roaming='0', peerdns='0', metric='20')
    if usb:
        network += section('interface', 'management', device=usb, proto='static', ipaddr='192.168.7.1', netmask='255.255.255.0')

    dhcp = section('dnsmasq', 'router_dns', domainneeded='1', boguspriv='1', rebind_protection='1',
                   local='/lan/', domain='lan', localservice='1', authoritative='1',
                   leasefile='/tmp/dhcp.leases', noresolv='1', server=['1.1.1.1', '8.8.8.8'],
                   interface=['lan', 'hotspot'] + (['management'] if usb else []), nonwildcard='1')
    for name in ('lan', 'hotspot'):
        dhcp += section('dhcp', name, interface=name, start='50', limit='151', leasetime='12h',
                        dhcpv6='disabled', ra='disabled', ndp='disabled')
    dhcp += section('dhcp', 'wan', interface='wan', ignore='1')
    if usb:
        dhcp += section('dhcp', 'management', interface='management', start='100', limit='51',
                        leasetime='12h', dhcp_option=['3', '6'], dhcpv6='disabled', ra='disabled')

    firewall = section('defaults', 'defaults', input='REJECT', output='ACCEPT', forward='REJECT', synflood_protect='1')
    zones = ['lan', 'hotspot', 'wan'] + (['management'] if usb else [])
    for name in zones:
        extra = dict(masq='1', mtu_fix='1') if name == 'wan' else {}
        firewall += section('zone', name, name=name, network=[name], input='REJECT', output='ACCEPT', forward='REJECT', **extra)
    for name in ('lan', 'hotspot'):
        firewall += section('forwarding', name + '_wan', src=name, dest='wan', family='ipv4')
        firewall += section('rule', name + '_dhcp', name=name + ' DHCP', src=name, proto='udp',
                            src_port='68', dest_port='67', family='ipv4', target='ACCEPT')
        firewall += section('rule', name + '_dns', name=name + ' DNS', src=name, proto='tcp udp',
                            dest_port='53', family='ipv4', target='ACCEPT')
        firewall += section('rule', name + '_web', name=name + ' settings', src=name, proto='tcp',
                            dest_ip='192.168.10.1', dest_port='8081', family='ipv4', target='ACCEPT')
    for name in ['lan'] + (['management'] if usb else []):
        firewall += section('rule', name + '_admin', name=name + ' administration', src=name,
                            proto='tcp', dest_port='22 80 443', family='ipv4', target='ACCEPT')
        firewall += section('rule', name + '_ping', name=name + ' ping', src=name,
                            proto='icmp', family='ipv4', target='ACCEPT')
    for name in ('wan', 'hotspot'):
        firewall += section('rule', name + '_ping', name=name + ' ping', src=name,
                            proto='icmp', icmp_type=['echo-request'], family='ipv4', target='ACCEPT')
    if usb:
        firewall += section('rule', 'management_dhcp', name='USB management DHCP', src='management',
                            proto='udp', src_port='68', dest_port='67', family='ipv4', target='ACCEPT')
    return dict(network=network, dhcp=dhcp, firewall=firewall)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lan-device', required=True)
    parser.add_argument('--modem-device', required=True)
    parser.add_argument('--usb-device', help='Optional existing USB gadget network device; no gadget is created')
    parser.add_argument('--radio', required=True, help='Existing dedicated 2.4 GHz UCI radio, e.g. radio0')
    parser.add_argument('--output', type=Path, default=Path('/tmp/stm32-router-candidate'))
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if not Path('/etc/openwrt_release').exists():
        parser.error('Run this tool on OpenWrt, after booting the board-specific image.')
    if not re.fullmatch(r'[A-Za-z0-9_]+', args.radio):
        parser.error('Invalid UCI radio name.')
    for name in (args.lan_device, args.usb_device):
        if name and not (Path('/sys/class/net') / name).exists():
            parser.error('Network device does not exist: ' + name)
    if not Path(args.modem_device).exists():
        parser.error('Modem sysfs device does not exist.')
    if run('uci', 'get', 'wireless.' + args.radio) != 'wifi-device':
        parser.error('Selected radio does not exist.')
    # Validate that ModemManager can identify the selected device before writing.
    run('mmcli', '-m', args.modem_device, '-J')
    generated = configs(args.lan_device, args.modem_device, args.usb_device)
    args.output = args.output.resolve()
    if args.output == Path('/etc/config') or Path('/etc/config') in args.output.parents:
        parser.error('Candidate directory must be outside /etc/config.')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, text in generated.items():
        atomic_write(args.output / name, text)
    atomic_write(args.output / 'wireless', Path('/etc/config/wireless').read_text())
    delta = args.output / 'delta'
    delta.mkdir()

    def uci(*arguments):
        return run('uci', '-c', str(args.output), '-t', str(delta), *arguments)

    # Keep board-generated radio path/calibration; disable its other APs.
    for line in uci('show', 'wireless').splitlines():
        if line.endswith('=wifi-iface'):
            key = line.split('=', 1)[0]
            if uci('get', key + '.device') == args.radio:
                uci('set', key + '.disabled=1')
    password = secrets.token_urlsafe(18)
    for key, value in {
        args.radio + '.disabled': '0', args.radio + '.country': 'AU',
        args.radio + '.channel': '6', args.radio + '.band': '2g', args.radio + '.htmode': 'HT20',
        'router_ap': 'wifi-iface', 'router_ap.device': args.radio, 'router_ap.network': 'hotspot',
        'router_ap.mode': 'ap', 'router_ap.ssid': 'STM32-LTE', 'router_ap.encryption': 'psk2',
        'router_ap.key': password, 'router_ap.isolate': '1', 'router_ap.disabled': '0',
    }.items():
        uci('set', 'wireless.' + key + '=' + value)
    uci('commit', 'wireless')
    packages = ('network', 'dhcp', 'firewall', 'wireless')
    for name in packages:
        uci('show', name)
    atomic_write(args.output / 'initial-wifi-password', password + '\n')
    if not args.install:
        print('Candidates written to ' + str(args.output) + '. No live configuration changed.')
        return
    state = Path('/etc/router-web')
    for name in packages:
        if run('uci', 'changes', name):
            raise RuntimeError('Apply/revert pending UCI edits before provisioning.')
    initialize(state)
    backup = state / 'before-openwrt'
    backup.mkdir(mode=0o700, exist_ok=False)  # Never overwrite the original recovery copy.
    for name in packages:
        shutil.copy2(Path('/etc/config') / name, backup / name)
    try:
        for name in packages:
            atomic_write(Path('/etc/config') / name, (args.output / name).read_text())
        run('fw4', 'check')
        atomic_write(state / 'initial-wifi-password', password + '\n')
        atomic_write(state / 'configured', '1\n')
    except Exception:
        for name in packages:
            shutil.copy2(backup / name, Path('/etc/config') / name)
        raise
    print('Configuration installed and firewall syntax checked; live networking was not restarted.')
    print('Backup: /etc/router-web/before-openwrt. Enable services and reboot from the serial console as documented.')


if __name__ == '__main__':
    main()
