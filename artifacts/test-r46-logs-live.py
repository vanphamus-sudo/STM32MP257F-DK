"""Run on the board: test syslog only against temporary loopback collectors."""
import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, '/usr/lib/router-web')
import openwrt_backend as backend
import router_logs as logs
import server

path=Path('/etc/config/system')
original=path.read_text()
initial=logs.settings(backend)
base=dict(local={k:v for k,v in initial['local'].items() if k!='file_supported'}, remote=initial['remote'])
marker='router-r46-'+uuid.uuid4().hex


def emit(text):
    subprocess.run(['logger','-t','router-log-test',text],check=True)


def apply(data):
    logs.save(data,backend,server.atomic_write)
    expected={'logd'} | ({'logfile'} if data['local']['file_enabled'] else set()) | ({'logremote'} if data['remote']['enabled'] else set())
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        instances=backend.ubus('service','list',name='log').get('log',{}).get('instances',{})
        if expected <= {name for name,value in instances.items() if value.get('running')}:
            time.sleep(2)
            return
        time.sleep(.2)
    raise AssertionError('Native log instances did not start: '+str(instances))


try:
    data=copy.deepcopy(base)
    data['local'].update(file_enabled=True,storage='memory',file_kib=1024)
    data['remote'].update(enabled=False,host='')
    apply(data)
    for _ in range(20):
        emit(marker+'-local')
        if logs.read(backend,source='file',search=marker)['lines']: break
        time.sleep(.2)
    assert logs.read(backend,source='file',search=marker)['lines'], 'Local file capture failed: '+json.dumps(logs.settings(backend))
    assert logs.read(backend,category='message',search=marker)['lines'], 'Memory capture failed'
    print('PASS native memory buffer and rotating RAM file',flush=True)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receiver:
        receiver.bind(('127.0.0.1',0));receiver.settimeout(2)
        data['remote']=dict(enabled=True,host='127.0.0.1',port=receiver.getsockname()[1],protocol='udp')
        apply(data);emit(marker+'-udp')
        end=time.monotonic()+8
        while time.monotonic()<end:
            try: packet=receiver.recv(65536)
            except socket.timeout: continue
            if (marker+'-udp').encode() in packet: break
        else: raise AssertionError('UDP forwarding failed')
    print('PASS native remote UDP syslog to temporary loopback collector',flush=True)
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as receiver:
        receiver.bind(('127.0.0.1',0));receiver.listen(1);receiver.settimeout(8)
        data['remote']=dict(enabled=True,host='127.0.0.1',port=receiver.getsockname()[1],protocol='tcp')
        apply(data)
        connection,_=receiver.accept()
        with connection:
            connection.settimeout(2);emit(marker+'-tcp');received=b'';end=time.monotonic()+8
            while time.monotonic()<end:
                try: packet=connection.recv(65536)
                except socket.timeout: continue
                if not packet: break
                received+=packet
                if (marker+'-tcp').encode() in received: break
            assert (marker+'-tcp').encode() in received, 'TCP forwarding failed'
    print('PASS native remote TCP syslog to temporary loopback collector',flush=True)
finally:
    server.atomic_write(path,original)
    backend.run('/etc/init.d/log','restart')
    assert path.read_text()==original
    print('Original logging configuration restored after loopback tests',flush=True)

# Enable a bounded temporary local file as requested; preserve remote destination.
base['local'].update(file_enabled=True,storage='memory',file_kib=1024)
apply(base)
emit(marker+'-ready')
print(json.dumps(dict(local=logs.settings(backend)['local'],remote_enabled=logs.settings(backend)['remote']['enabled'])),flush=True)
