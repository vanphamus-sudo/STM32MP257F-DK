"""Verify installed HTTP assets and authenticated handlers without changing login credentials."""
import http.client
import json
import socket
import sys
import threading
import time
import uuid

sys.path.insert(0,'/usr/lib/router-web')
import server
import router_logs
import openwrt_backend as backend
import version_info

assert version_info.VERSION=='1.0.0-r46'
for path, marker in (('/','Local Log'),('/logs.html','Live Log'),('/logs.js','logs-output')):
    client=http.client.HTTPConnection('192.168.7.1',8081,timeout=10)
    client.request('GET',path)
    response=client.getresponse();body=response.read().decode();client.close()
    assert response.status==200 and marker in body
    print('PASS installed asset',path)
client=http.client.HTTPConnection('192.168.7.1',8081,timeout=10)
client.request('GET','/api/logs?category=message')
response=client.getresponse();response.read();client.close()
assert response.status==401
print('PASS running service rejects unauthenticated log reads')

# Isolated handler instance with a temporary session; real credentials stay untouched.
token=uuid.uuid4().hex
server.SESSIONS[token]=dict(csrf=uuid.uuid4().hex,expires=time.monotonic()+30)
http_server=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
thread=threading.Thread(target=http_server.serve_forever,daemon=True);thread.start()
try:
    for category in ('message','application','kernel','audit'):
        client=http.client.HTTPConnection('127.0.0.1',http_server.server_port,timeout=10)
        client.request('GET','/api/logs?category='+category+'&limit=20',headers={'Host':'192.168.7.1:8081','Cookie':'router_session='+token})
        response=client.getresponse();value=json.loads(response.read());client.close()
        assert response.status==200 and isinstance(value['lines'],list)
        print('PASS authenticated',category,'view',len(value['lines']),'records')
finally:
    http_server.shutdown();http_server.server_close();thread.join(5);server.SESSIONS.clear()

settings=router_logs.settings(backend)
assert settings['local']['file_enabled'] and settings['local']['storage']=='memory'
assert not settings['remote']['enabled']
assert router_logs.read(backend,source='file')['lines']
assert json.loads(backend.run('ubus','call','network.interface.wan','status'))['up']
with socket.create_connection(('192.168.7.1',11111),timeout=5) as connection:
    connection.sendall(b'AT$VERSION\r')
    assert b'r46' in connection.recv(2048)
print('PASS local file, remote forwarding off, WAN up and AT version r46')
