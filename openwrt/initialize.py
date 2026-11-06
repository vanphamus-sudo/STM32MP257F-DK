"""Create persistent credentials on the device, never in the firmware image."""
import hashlib
import json
import os
from pathlib import Path
import secrets

from server import atomic_write


def initialize(state=Path('/etc/router-web')):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state, 0o700)
    if not (state / 'credentials.json').exists():
        # Preserve the existing project's requested first-login convention.
        password = 'admin'
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 250000).hex()
        atomic_write(state / 'initial-password', password + '\n')
        atomic_write(state / 'credentials.json', json.dumps(dict(username='admin', salt=salt, hash=digest)))


if __name__ == '__main__':
    initialize()
