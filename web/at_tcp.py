#!/usr/bin/env python3
"""One-client, line-oriented LTE AT server; software commands never reach the modem."""
import socketserver
import threading
import time
import uuid
import at_audit
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
        peer = dict(connection=uuid.uuid4().hex, client_ip=self.client_address[0],
                    client_port=self.client_address[1], server_port=self.server.server_address[1])
        at_audit.record('connection_open', **peer)
        if not self.server.owner.acquire(blocking=False):
            at_audit.record('connection_rejected', reason='single_client_busy', **peer)
            at_audit.record('connection_closed', reason='single_client_busy', **peer)
            return
        reason = 'client_closed'
        phase = 'receive'
        sequence = 0
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
                        if not oversized and not pending:
                            continue
                        sequence += 1
                        started = time.monotonic()
                        if oversized:
                            at_audit.record('command_rejected', command_id=sequence, reason='too_long', **peer)
                            reply = b'\r\nERROR: COMMAND TOO LONG\r\n'
                        else:
                            try:
                                command = pending.decode('ascii').strip()
                                if not command.upper().startswith('AT') or len(command) < 2 or any(ord(c) < 32 or ord(c) > 126 for c in command):
                                    raise ValueError()
                                at_audit.record('command_received', command_id=sequence,
                                                command=at_audit.command_label(command), **peer)
                                if version_info.reserved_response(command) is None and not at_audit.prepare_modem():
                                    reply = b'\r\nERROR: AUDIT PRIVACY GUARD UNAVAILABLE\r\n'
                                else:
                                    reply = response(command)
                            except (UnicodeError, ValueError):
                                at_audit.record('command_rejected', command_id=sequence, reason='invalid_command', **peer)
                                reply = b'\r\nERROR: INVALID AT COMMAND\r\n'
                        pending.clear()
                        oversized = False
                        self.request.settimeout(5)
                        phase = 'send'
                        result = dict(command_id=sequence, result=at_audit.outcome(reply),
                                      duration_ms=round((time.monotonic()-started)*1000), reply_bytes=len(reply))
                        try:
                            self.request.sendall(reply)
                        except OSError:
                            at_audit.record('command_completed', delivered=False, **result, **peer)
                            raise
                        at_audit.record('command_completed', delivered=True, **result, **peer)
                        phase = 'receive'
                        self.request.settimeout(self.server.idle_seconds)
                    elif not oversized:
                        pending.append(byte)
                        if len(pending) > 256:
                            oversized = True
                            pending.clear()
        except TimeoutError:
            reason = 'reply_timeout' if phase == 'send' else 'idle_timeout'
        except (OSError, ConnectionError):
            reason = 'connection_error'
        finally:
            self.server.owner.release()
            at_audit.record('connection_closed', reason=reason, **peer)


if __name__ == '__main__':
    with Server(('0.0.0.0', 11111)) as server:
        print('LTE AT server listening on TCP 11111; one client, 60s idle timeout', flush=True)
        server.serve_forever()
