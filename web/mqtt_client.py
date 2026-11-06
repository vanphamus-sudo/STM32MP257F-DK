#!/usr/bin/env python3
"""Supervised IRMS MQTT client. Configuration contains credentials; keep mode 0600."""
import argparse
import json
import logging
from pathlib import Path
import queue
import signal
import ssl
import threading

from mqtt_data import RouterData, atomic_json
from mqtt_protocol import MAX_PAYLOAD, Protocol


def validate(config):
    if type(config.get('enabled')) is not bool:
        raise ValueError('enabled must be boolean')
    if not config['enabled']:
        return config
    for key in ('host', 'serial', 'username', 'password'):
        if not isinstance(config.get(key), str) or not config[key] or '\x00' in config[key]:
            raise ValueError('Configure ' + key)
    if type(config.get('port', 8883)) is not int or not 1 <= config.get('port', 8883) <= 65535:
        raise ValueError('Invalid broker port')
    if type(config.get('verify_hostname', True)) is not bool:
        raise ValueError('verify_hostname must be boolean')
    return config


def run(config, stop):
    import paho.mqtt.client as mqtt
    kwargs = dict(client_id=config['serial'], protocol=mqtt.MQTTv311)
    if hasattr(mqtt, 'CallbackAPIVersion'):
        kwargs['callback_api_version'] = mqtt.CallbackAPIVersion.VERSION2
    client = mqtt.Client(**kwargs)
    client.username_pw_set(config['username'], config['password'])
    if config.get('tls_enabled', True):
        context = ssl.create_default_context(cafile=config.get('ca_file') or None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = config.get('verify_hostname', True)
        client.tls_set_context(context)
    client.reconnect_delay_set(1, 60)
    client.max_queued_messages_set(200)
    client.max_inflight_messages_set(20)
    client.will_set('/TX/' + config['serial'] + '/LOGOUT', b'', qos=1)
    incoming = queue.Queue(maxsize=200)
    connected = threading.Event()
    acknowledgements = queue.Queue(maxsize=500)
    pending, samples = {}, {}
    runtime = dict(state='connecting', queued=0, broker_acknowledged=0)
    def publish(topic, payload):
        info = client.publish(topic, payload, qos=1, retain=False)
        if info.rc == 0:
            pending[info.mid] = topic
            runtime['queued'] += 1
            if not '/PROXY/' in topic:
                samples[topic] = dict(payload=json.loads(payload) if payload else None, broker_acknowledged=False)
        return info
    protocol = Protocol(config['serial'], RouterData(config), publish)

    def on_connect(client, userdata, flags, reason, properties=None):
        if reason != 0:
            runtime['state'] = 'broker rejected connection'
            logging.warning('Broker rejected MQTT connection: %s', reason)
            return
        connected.set()
        runtime['state'] = 'subscribing'
        # Login must follow SUBACK so a fast server's response cannot be lost.
        protocol.logged_in = False
        protocol.last.clear()
        client.subscribe('/RX/' + config['serial'] + '/#', qos=1)

    ready = threading.Event()

    def on_subscribe(client, userdata, mid, reasons, properties=None):
        if any(getattr(reason, 'is_failure', False) or (isinstance(reason, int) and reason >= 128) for reason in reasons):
            runtime['state'] = 'broker rejected subscription'
            logging.error('Broker refused IRMS subscription')
            return
        ready.set()
        runtime['state'] = 'connected'

    def on_disconnect(*args):
        connected.clear()
        ready.clear()
        runtime['state'] = 'disconnected'

    def on_publish(client, userdata, mid, *args):
        try:
            acknowledgements.put_nowait(mid)
        except queue.Full:
            pass

    def on_message(client, userdata, message):
        if len(message.payload) <= MAX_PAYLOAD:
            try:
                incoming.put_nowait((message.topic, message.payload, message.retain))
            except queue.Full:
                logging.warning('MQTT command queue full; dropping message')

    client.on_connect, client.on_disconnect = on_connect, on_disconnect
    client.on_subscribe, client.on_message = on_subscribe, on_message
    client.on_publish = on_publish
    client.connect_async(config['host'], config.get('port', 8883), 60)
    client.loop_start()
    last_runtime = 0
    try:
        while not stop.wait(0.2):
            import time
            while not acknowledgements.empty():
                topic = pending.pop(acknowledgements.get_nowait(), None)
                if topic:
                    runtime['broker_acknowledged'] += 1
                    if topic in samples:
                        samples[topic]['broker_acknowledged'] = True
            if time.monotonic() - last_runtime >= 2:
                state = 'waiting for IRMS login' if connected.is_set() and ready.is_set() and not protocol.logged_in else runtime['state']
                atomic_json(Path('/tmp/router-mqtt-status.json'), dict(runtime, state=state, updated_at=int(time.time())))
                atomic_json(Path('/tmp/router-mqtt-samples.json'), samples)
                last_runtime = time.monotonic()
            if not connected.is_set() or not ready.is_set():
                protocol.adapter.proxies.close_all()
                while not incoming.empty():
                    incoming.get_nowait()
                continue
            try:
                for _ in range(20):
                    try:
                        message = incoming.get_nowait()
                    except queue.Empty:
                        break
                    protocol.receive(*message)
                protocol.tick()
            except (ValueError, OSError, RuntimeError) as error:
                logging.warning('MQTT data collection failed: %s', error)
                stop.wait(5)
    finally:
        protocol.adapter.proxies.close_all()
        if connected.is_set():
            client.publish('/TX/' + config['serial'] + '/LOGOUT', b'', qos=1).wait_for_publish(timeout=3)
        client.disconnect()
        client.loop_stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/router-web/mqtt.json'))
    args = parser.parse_args()
    config = validate(json.loads(args.config.read_text()))
    if not config['enabled']:
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(config, stop)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
