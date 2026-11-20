"""Bounded local log viewing and native OpenWrt syslog configuration."""
import ipaddress
from pathlib import Path
import re
import shlex
import subprocess
import time

FILES = {'memory': '/var/log/router/messages.log', 'persistent': '/root/router-logs/messages.log'}
MAX_BYTES = 256 * 1024


def system_section(backend):
    # rpcd's UCI view may retain a loaded package after a direct file transaction.
    # Read the committed CLI view so save/readback and logd use the same config.
    sections = {}
    for line in backend.run('uci', '-q', 'show', 'system').splitlines():
        key, separator, value = line.partition('=')
        if not separator or not key.startswith('system.'):
            continue
        parts = key.removeprefix('system.').split('.', 1)
        section = sections.setdefault(parts[0], {})
        values = shlex.split(value)
        section[parts[1] if len(parts) == 2 else '.type'] = values[0] if len(values) == 1 else values
    for name, section in sections.items():
        if section.get('.type') == 'system':
            return name, section
    raise RuntimeError('System logging configuration is unavailable.')


def settings(backend):
    _, section = system_section(backend)
    path = section.get('log_file', '')
    return dict(local=dict(buffer_kib=int(section.get('log_buffer_size') or section.get('log_size') or 64),
                           file_enabled=bool(path), storage=next((k for k, v in FILES.items() if v == path), 'memory'),
                           file_kib=int(section.get('log_size') or 1024), file_supported=not path or path in FILES.values()),
                remote=dict(enabled=bool(section.get('log_ip')) and section.get('log_remote', '1') != '0',
                            host=section.get('log_ip', ''), port=int(section.get('log_port') or 514),
                            protocol=section.get('log_proto', 'udp')))


def number(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')


def validate(data):
    if set(data) != {'local', 'remote'} or not isinstance(data['local'], dict) or not isinstance(data['remote'], dict):
        raise ValueError('Invalid logging settings.')
    local, remote = data['local'], data['remote']
    if set(local) != {'buffer_kib', 'file_enabled', 'storage', 'file_kib'} or set(remote) != {'enabled', 'host', 'port', 'protocol'}:
        raise ValueError('Invalid logging fields.')
    if type(local['file_enabled']) is not bool or type(remote['enabled']) is not bool:
        raise ValueError('Choose whether file and remote logging are enabled.')
    number(local['buffer_kib'], 64, 4096, 'Memory buffer size in KiB')
    number(local['file_kib'], 128, 16384, 'Log file size in KiB')
    number(remote['port'], 1, 65535, 'Syslog port')
    if local['storage'] not in FILES or remote['protocol'] not in ('udp', 'tcp'):
        raise ValueError('Choose a supported storage location and syslog transport.')
    host = remote['host']
    if not isinstance(host, str) or len(host) > 253 or host != host.strip():
        raise ValueError('Enter a syslog server IP address or hostname.')
    if host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in host.split('.')):
                raise ValueError('Enter a syslog server IP address or hostname.') from None
    elif remote['enabled']:
        raise ValueError('Enter the remote syslog server before enabling forwarding.')


def save(data, backend, atomic_write):
    validate(data)
    name, current = system_section(backend)
    local, remote = data['local'], data['remote']
    options = dict(log_buffer_size=local['buffer_kib'], log_size=local['file_kib'],
                   log_remote='1' if remote['enabled'] else '0', log_ip=remote['host'],
                   log_port=remote['port'], log_proto=remote['protocol'], log_trailer_null='0')
    edits = [('set', 'system.' + name + '.' + key, value) for key, value in options.items()]
    if local['file_enabled']:
        edits.append(('set', 'system.' + name + '.log_file', FILES[local['storage']]))
    elif current.get('log_file'):
        edits.append(('delete', 'system.' + name + '.log_file', None))
    backend.transaction('system', edits, lambda: backend.run('/etc/init.d/log', 'restart'), atomic_write)
    return dict(settings=settings(backend), message='Logging settings saved. The log service restarted; the memory buffer may start fresh.')


def redact(text, backend):
    # Mask known cellular credentials and common textual secret assignments.
    wan = backend.values('network').get('wan', {})
    for key in ('password', 'pincode'):
        secret = wan.get(key)
        if isinstance(secret, str) and secret:
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)((?:password|passwd|pincode|token|secret)\s*[=:]\s*)("[^"]*"|\'[^\']*\'|[^\s,;]+)', r'\1[redacted]', text)
    text = re.sub(r'(?i)(AT\+CPIN\s*=)[^\r\n]+', r'\1[redacted]', text)
    return text


def read(backend, category='message', source='buffer', limit=300, search=''):
    if category not in ('message', 'application', 'kernel', 'audit') or source not in ('buffer', 'file'):
        raise ValueError('Choose a supported log category and source.')
    number(limit, 1, 1000, 'Displayed line count')
    if not isinstance(search, str) or len(search) > 100 or any(ord(c) < 32 for c in search):
        raise ValueError('Search must be up to 100 characters without control characters.')
    note = 'Current boot only; old records roll out of the memory buffer.'
    if source == 'file':
        _, section = system_section(backend)
        filename = section.get('log_file', '')
        if not filename:
            return dict(lines=[], category=category, source=source, updated_at=time.time(), truncated=False,
                        note='Local file logging is disabled. Enable it under Local Log settings.')
        if filename not in FILES.values():
            raise ValueError('The configured log file is outside the managed log locations.')
        try:
            with Path(filename).open('rb') as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - MAX_BYTES))
                raw = stream.read(MAX_BYTES)
            if size > MAX_BYTES:
                raw = raw.partition(b'\n')[2]
        except FileNotFoundError:
            raw, size = b'', 0
        note = 'Current local log file; showing at most the last 256 KiB. Rotated files are not included.'
    else:
        command = ['dmesg'] if category == 'kernel' else ['logread', '-l', '1000']
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        if result.returncode:
            raise RuntimeError('Log source is unavailable.')
        raw, size = result.stdout[-MAX_BYTES:], len(result.stdout)
    text = redact(raw.decode('utf-8', errors='replace'), backend)
    lines = text.splitlines()
    if not (category == 'kernel' and source == 'buffer'):
        audit = re.compile(r'\bauth(?:priv)?\.|\baudit\b|router-at-audit|avc:\s*denied', re.I)
        if category == 'kernel':
            lines = [line for line in lines if 'kern.' in line]
        elif category == 'audit':
            lines = [line for line in lines if audit.search(line)]
        elif category == 'application':
            lines = [line for line in lines if 'kern.' not in line and not audit.search(line)]
    if search:
        lines = [line for line in lines if search.casefold() in line.casefold()]
    truncated = size > MAX_BYTES or len(lines) > limit
    return dict(lines=lines[-limit:], category=category, source=source, updated_at=time.time(),
                truncated=truncated, note=note + (' Audit shows existing authentication/audit records; it does not enable a separate audit subsystem.' if category == 'audit' else ''))
