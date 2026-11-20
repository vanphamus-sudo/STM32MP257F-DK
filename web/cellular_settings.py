"""Authenticated cellular connection settings; never return saved passwords."""
import re


def status(backend):
    wan = backend.values('network').get('wan', {})
    return dict(apn=wan.get('apn', ''), username=wan.get('username', ''),
                password_saved=bool(wan.get('password')), auth=wan.get('allowedauth', 'none'),
                iptype=wan.get('iptype', 'ipv4'))


def save(data, backend, atomic_write):
    if set(data) != {'apn', 'username', 'password', 'clear_password', 'auth', 'iptype'}:
        raise ValueError('Invalid cellular settings.')
    if not isinstance(data['apn'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,99}', data['apn']):
        raise ValueError('Enter an APN using letters, numbers, dots or hyphens (up to 100 characters).')
    for key in ('username', 'password'):
        value = data[key]
        if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError('Cellular credentials must be up to 256 printable ASCII characters.')
        if any(c in value for c in ',\'"\\'):
            raise ValueError('This modem connection service does not support commas, quotes or backslashes in credentials.')
    if type(data['clear_password']) is not bool or (data['clear_password'] and data['password']):
        raise ValueError('Choose either a new password or clear saved password.')
    if data['auth'] not in ('none', 'pap', 'chap', 'pap|chap'):
        raise ValueError('Choose a supported authentication method.')
    if data['iptype'] not in ('ipv4', 'ipv6', 'ipv4v6'):
        raise ValueError('Choose IPv4, IPv6 or IPv4/IPv6.')
    wan = backend.values('network').get('wan', {})
    edits = [('set', 'network.wan.' + key, data[field]) for key, field in
             (('apn', 'apn'), ('username', 'username'), ('allowedauth', 'auth'), ('iptype', 'iptype'))]
    if data['password']:
        edits.append(('set', 'network.wan.password', data['password']))
    elif data['clear_password'] and wan.get('password'):
        edits.append(('delete', 'network.wan.password', None))
    def reconnect():
        backend.run('ifdown', 'wan')
        backend.run('ifup', 'wan')
    backend.transaction('network', edits, reconnect, atomic_write)
    return dict(settings=status(backend), message='Saved. Cellular reconnection started; check Network overview for the result.')
