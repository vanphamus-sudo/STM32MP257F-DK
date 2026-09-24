#!/usr/bin/env python3
"""Explicit maintenance action: reset web login to admin/admin; restart web afterward."""
import hashlib
import json
import os
from pathlib import Path
import secrets

state = Path('/var/lib/router-web')
salt = secrets.token_hex(16)
digest = hashlib.pbkdf2_hmac('sha256', b'admin', bytes.fromhex(salt), 250000).hex()
temporary = state / 'credentials.reset'
with temporary.open('w') as handle:
    os.chmod(temporary, 0o600)
    json.dump(dict(username='admin', salt=salt, hash=digest), handle)
    handle.flush()
    os.fsync(handle.fileno())
temporary.replace(state / 'credentials.json')
initial = state / 'initial-password'
initial.write_text('admin\n')
os.chmod(initial, 0o600)
