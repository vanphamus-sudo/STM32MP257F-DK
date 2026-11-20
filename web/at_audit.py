"""Privacy-conscious audit events for the remote AT TCP service."""
from datetime import datetime, timezone
import json
import logging
import re
import subprocess

try:
    import syslog
except ImportError:  # Host-side tests on Windows.
    syslog = None


def command_label(command):
    """Keep the AT operation but hide all parameter values conservatively."""
    match = re.match(r'(?i)^(AT(?:[+$^%#][A-Z][A-Z0-9_/-]*|&?[A-Z])?)', command)
    if not match:
        return '[invalid command]'
    operation = match[1].upper()[:64]
    suffix = command[len(match[1]):]
    if suffix in ('', '?', '=?'):
        return operation + suffix
    return operation + ('=[redacted]' if suffix.startswith('=') else ' [redacted]')


def record(event, **fields):
    value = dict(timestamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                 event=event, transport='tcp', **fields)
    # JSON escaping keeps client-controlled text on one physical log line.
    message = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    if syslog is not None:
        syslog.openlog('router-at-audit', syslog.LOG_PID, syslog.LOG_AUTHPRIV)
        syslog.syslog(syslog.LOG_NOTICE, message)
    else:
        logging.getLogger('router-at-audit').info(message)


def prepare_modem():
    # --debug is required for AT access, but DEBUG verbosity echoes raw secrets.
    # Set operational INFO before forwarding, and fail closed if that fails.
    try:
        result = subprocess.run(['mmcli', '--set-logging=INFO'], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def outcome(reply):
    if reply.rstrip().endswith(b'\r\nOK'):
        return 'ok'
    if b'COMMAND TOO LONG' in reply:
        return 'too_long'
    if b'INVALID AT COMMAND' in reply:
        return 'invalid_command'
    if b'PRIVACY GUARD' in reply:
        return 'privacy_guard_failed'
    if b'UNKNOWN SOFTWARE COMMAND' in reply:
        return 'unknown_software_command'
    if b'BUSY OR UNAVAILABLE' in reply:
        return 'busy_or_unavailable'
    if b'MODEM UNAVAILABLE' in reply:
        return 'modem_unavailable'
    return 'modem_error'
