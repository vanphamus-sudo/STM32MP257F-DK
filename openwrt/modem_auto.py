"""Select supported USB modems without relying on port or ModemManager numbers."""
import json
import logging
from pathlib import Path
import subprocess
import time

MODELS = {'0316': 'RG255C-GL', '030b': 'EM060K-GL', '0801': 'RM520N-GL'}
STATE = Path('/etc/router-web/modem-auto.json')
STATUS = Path('/var/run/router-modem-auto.json')
LOG = logging.getLogger('router-modem')


def run(*args, optional=False):
    result = subprocess.run(args, text=True, capture_output=True, timeout=20)
    if result.returncode and not optional:
        raise RuntimeError('Command failed: ' + args[0])
    return result.stdout.strip() if result.returncode == 0 else ''


def discover(root=Path('/sys/bus/usb/devices')):
    found = []
    for device in sorted(root.iterdir()):
        try:
            if (device / 'idVendor').read_text().strip() != '2c7c':
                continue
            product = (device / 'idProduct').read_text().strip()
            if product not in MODELS:
                continue
            # Both QMI and MBIM expose a network interface. Wait for binding.
            if not any(device.glob('*:*/net/*')):
                continue
            found.append(dict(model=MODELS[product], device=str(device.resolve())))
        except OSError:
            continue
    return found


def choose(candidates, current):
    return next((item for item in candidates if item['device'] == current),
                candidates[0] if len(candidates) == 1 else None)


def mode_for(model, current, saved=None):
    mode = dict(current if saved is None else saved)
    # An LTE-only EM060K cannot use the RG255C's forced 5G setting.
    if model == 'EM060K-GL':
        mode = {'allowedmode': '4g', 'preferredmode': ''}
    return mode


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {'profiles': {}}


def reconcile(state):
    current = run('uci', '-q', 'get', 'network.wan.device', optional=True)
    candidates = discover()
    selected = choose(candidates, current)
    if selected is None:
        write_json(STATUS, dict(state='absent' if not candidates else 'ambiguous', candidates=candidates))
        return
    model, device = selected['model'], selected['device']
    mode = {key: run('uci', '-q', 'get', 'network.wan.' + key, optional=True)
            for key in ('allowedmode', 'preferredmode')}
    previous = state.get('model')
    profiles = dict(state.get('profiles', {}))
    if previous and previous != model:
        profiles[previous] = mode
    saved = profiles.get(model) if previous != model else None
    if previous and previous != model and saved is None and model in ('RG255C-GL', 'RM520N-GL'):
        saved = {'allowedmode': '4g|5g', 'preferredmode': '5g'}
    target = mode_for(model, mode, saved)
    changes = {}
    if current != device:
        changes['device'] = device
    if run('uci', '-q', 'get', 'network.wan.proto', optional=True) != 'modemmanager':
        changes['proto'] = 'modemmanager'
    changes.update({key: value for key, value in target.items() if value != mode[key]})
    if changes:
        # Avoid committing unrelated settings currently staged by the UI.
        pending = run('uci', 'changes', 'network')
        if pending:
            write_json(STATUS, dict(selected, state='waiting-for-settings-save'))
            return
        run('ifdown', 'wan', optional=True)
        for key, value in changes.items():
            if value:
                run('uci', 'set', 'network.wan.' + key + '=' + value)
            else:
                run('uci', '-q', 'delete', 'network.wan.' + key, optional=True)
        run('uci', 'commit', 'network')
    profiles[model] = target
    new_state = dict(state, model=model, device=device, profiles=profiles)
    if new_state != state:
        write_json(STATE, new_state)
        state.update(new_state)
    if changes:
        run('ifup', 'wan')
        LOG.warning('Selected %s at %s', model, device)
    write_json(STATUS, dict(selected, state='selected', modes=target))


def main():
    logging.basicConfig(level=logging.INFO)
    state = load_state()
    while True:
        try:
            run('/usr/sbin/router-modem-bind')
            reconcile(state)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            LOG.warning('Modem detection retry: %s', error)
        time.sleep(5)


if __name__ == '__main__':
    main()
