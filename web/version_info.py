"""Immutable identity for this software release, shared by UI and AT replies."""
VERSION = '1.0.0-r44'
CREATED_AT = '2026-11-13T11:00:28+11:00'
VERSION_STRING = 'STM32 Router ' + VERSION + ' | created ' + CREATED_AT


def info():
    return dict(version=VERSION, created_at=CREATED_AT, string=VERSION_STRING)


def at_response():
    return ('\r\n' + VERSION_STRING + '\r\nOK\r\n').encode('ascii')


def reserved_response(command):
    if not command.upper().startswith('AT$'):
        return None
    if command.upper() == 'AT$VERSION':
        return at_response()
    return b'\r\nERROR: UNKNOWN SOFTWARE COMMAND\r\n'
