#!/usr/bin/env python3
"""One-client, line-oriented LTE AT server; software commands never reach the modem."""
import socketserver
import threading
import openwrt_backend as modem
import version_info


def response(command):
    reserved = version_info.reserved_response(command)
    if reserved is not None:
        return reserved
    try:
        result = modem.send_at({'command': command})
        if not result['ok']:
            return b'\r\nERROR: MODEM COMMAND FAILED\r\n'
        text = result['response']
        if text.startswith("response: '") and text.endswith("'"):
            text = text[11:-1]
        text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
        return ('\r\n' + text + '\r\nOK\r\n').encode('utf-8')
    except ValueError:
        return b'\r\nERROR: INVALID AT COMMAND\r\n'
    except RuntimeError:
        return b'\r\nERROR: MODEM BUSY OR UNAVAILABLE\r\n'
    except Exception:
        return b'\r\nERROR: MODEM UNAVAILABLE\r\n'


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    def __init__(self, address, idle_seconds=60):
        self.owner = threading.Lock()
        self.idle_seconds = idle_seconds
        super().__init__(address, Handler)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.owner.acquire(blocking=False):
            return
        try:
            self.request.settimeout(self.server.idle_seconds)
            pending = bytearray()
            oversized = False
            while True:
                data = self.request.recv(4096)
                if not data:
                    return
                for byte in data:
                    if byte in (10, 13):
                        if oversized:
                            reply = b'\r\nERROR: COMMAND TOO LONG\r\n'
                        elif not pending:
                            continue
                        else:
                            try:
                                command = pending.decode('ascii').strip()
                                if any(ord(c) < 32 or ord(c) > 126 for c in command):
                                    raise ValueError()
                                reply = response(command)
                            except (UnicodeError, ValueError):
                                reply = b'\r\nERROR: INVALID AT COMMAND\r\n'
                        pending.clear()
                        oversized = False
                        self.request.settimeout(5)
                        self.request.sendall(reply)
                        self.request.settimeout(self.server.idle_seconds)
                    elif not oversized:
                        pending.append(byte)
                        if len(pending) > 256:
                            oversized = True
                            pending.clear()
        except (OSError, ConnectionError):
            pass
        finally:
            self.server.owner.release()


if __name__ == '__main__':
    with Server(('0.0.0.0', 11111)) as server:
        print('LTE AT server listening on TCP 11111; one client, 60s idle timeout', flush=True)
        server.serve_forever()
