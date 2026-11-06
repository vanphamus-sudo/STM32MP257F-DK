"""Best-effort local event producer; MQTT daemon owns delivery and alarm ACKs."""
import json
from pathlib import Path
import time
import uuid

from mqtt_data import atomic_json


def web_login(username, address, success, state=Path('/etc/router-web')):
    try:
        config = json.loads((state / 'mqtt.json').read_text())
        if not config.get('enabled'):
            return
        queue = state / 'mqtt-state/outbox'
        if queue.exists() and sum(1 for _ in queue.glob('*.json')) >= 1000:
            return
        data = dict(username=str(username)[:256], mode='local', authority='admin', name='',
                    ip=address, mac='', time=str(int(time.time())), methods='web',
                    result='succeed' if success else 'fail')
        atomic_json(queue / (uuid.uuid4().hex + '.json'), dict(topic='EVENT/LOGINFO', data=data))
    except (OSError, ValueError):
        # Remote reporting must never prevent local management access.
        pass
