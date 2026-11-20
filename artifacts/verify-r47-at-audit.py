"""Board-side safe AT audit verification; no SIM unlock or configuration command."""
import json
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0,'/usr/lib/router-web')
import router_logs
import openwrt_backend as backend
import version_info

assert version_info.VERSION=='1.0.0-r47'
secret='audit-private-'+uuid.uuid4().hex
start=time.time()


def receive(client):
    data=b''
    while not data.endswith(b'\r\nOK\r\n') and b'\r\nERROR:' not in data:
        part=client.recv(8192)
        if not part:break
        data+=part
    return data


with socket.create_connection(('192.168.7.1',11111),timeout=15) as client:
    client.settimeout(20)
    client.sendall(b'ATI\r')
    assert receive(client).endswith(b'\r\nOK\r\n'),'ATI failed after INFO privacy guard'
    with socket.create_connection(('192.168.7.1',11111),timeout=3) as second:
        second.settimeout(3)
        try: assert second.recv(1)==b''
        except ConnectionResetError:pass
    # Unknown vendor command is rejected by the modem; no credential attempt.
    client.sendall(('AT+ROUTERAUDITTEST="'+secret+'"\r').encode())
    assert b'ERROR:' in receive(client)
    client.sendall(b'AT$VERSION\r')
    assert b'r47' in receive(client)
time.sleep(.4)
raw=subprocess.check_output(['logread','-l','1000']).decode(errors='replace')
assert secret not in raw,'Private parameter leaked into raw system logs'
events=[]
for line in router_logs.read(backend,category='audit',limit=1000)['lines']:
    if 'router-at-audit' in line and '{' in line:
        value=json.loads(line[line.index('{'):])
        if value.get('event')=='command_received' and value.get('command')=='AT+ROUTERAUDITTEST=[redacted]':
            selected=value['connection']
        events.append(value)
assert 'selected' in locals(),'Masked audit record missing'
events=[event for event in events if event.get('connection')==selected]
assert any(event['event']=='connection_open' for event in events)
assert any(event['event']=='connection_closed' and event['reason']=='client_closed' for event in events)
assert any(event['event']=='command_completed' and event['result']=='ok' and event['delivered'] for event in events)
assert any(event['event']=='command_completed' and event['result']=='modem_error' for event in events)
assert all(event.get('client_ip')=='192.168.7.1' and 'timestamp' in event for event in events)
file_lines=router_logs.read(backend,category='audit',source='file',limit=1000)['lines']
assert any(selected in line for line in file_lines),'Audit events missing from local file'
assert secret not in '\n'.join(file_lines)
assert json.loads(backend.run('ubus','call','network.interface.wan','status'))['up']
print(json.dumps(dict(result='passed',version=version_info.VERSION,audit_events=len(events),
                     client_ip_verified=True,commands_masked=True,raw_log_secret_check=True,
                     local_file_capture=True,successful_and_failed_commands=True,wan_up=True)))
