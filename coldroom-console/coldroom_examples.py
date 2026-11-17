#!/usr/bin/env python3
"""ColdRoom - camaras frigorificas de exemplo publicadas no Mosquitto.

Cada camara de EXAMPLE_DEVICES (config.py) comporta-se como um Pico W:
  - ligacao MQTT propria, com last will '<topico>/status' = 'offline' (retido)
  - publica 'online' ao ligar e o estado em '<topico>/state' (retido) a cada 5 s
  - payload no mesmo formato JSON do Pico W
Os valores sao gerados por demo_sim.py (ficticios).

    python3 coldroom_examples.py            # usa config.py
    sudo systemctl status coldroom-examples # quando instalado como servico
"""
import json
import signal
import sys
import threading
import time

import config
import demo_sim


def cfg(name, default=None):
    return getattr(config, name, default)


def pi_health():
    """IP e temperatura do CPU do Raspberry Pi (onde correm as camaras de exemplo)."""
    out = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["mcu_temp_c"] = round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        pass
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # nao envia nada; so escolhe a interface
        out["ip"] = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    return out


def make_client(mqtt, client_id):
    try:  # paho-mqtt 2.x
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def main():
    host = cfg("MQTT_HOST")
    examples = cfg("EXAMPLE_DEVICES", []) or []
    if not host:
        print("[exemplos] MQTT_HOST nao definido no config.py - nada a fazer")
        return 1
    if not examples:
        print("[exemplos] EXAMPLE_DEVICES vazio - nada a publicar")
        # Fica parado em vez de sair, para o systemd nao o reiniciar em ciclo
        signal.sigwait([signal.SIGTERM, signal.SIGINT])
        return 0
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("[exemplos] ERRO: paho-mqtt nao instalado (sudo apt install python3-paho-mqtt)")
        return 1

    port = int(cfg("MQTT_PORT", 1883))
    devices = []
    for base, sp in examples:
        sim = demo_sim.new_sim(base, sp, example=True)
        name = sim["base"].split("/")[-1]
        client = make_client(mqtt, "coldroom-exemplo-%s" % name)
        if cfg("MQTT_USER"):
            client.username_pw_set(cfg("MQTT_USER"), cfg("MQTT_PASSWORD"))
        if cfg("MQTT_TLS", False):
            client.tls_set(ca_certs=cfg("MQTT_CA_FILE"))
        status_topic = sim["base"] + "/status"
        client.will_set(status_topic, "offline", qos=1, retain=True)

        def on_connect(c, userdata, flags, rc, *args, _st=status_topic, _n=name):
            if getattr(rc, "value", rc) == 0:
                c.publish(_st, "online", qos=1, retain=True)
                print("[exemplos] %s ligado" % _n.upper())
            else:
                print("[exemplos] %s recusado pelo broker (rc=%s)" % (_n.upper(), rc))

        client.on_connect = on_connect
        client.reconnect_delay_set(min_delay=1, max_delay=15)
        client.connect_async(host, port, keepalive=30)
        client.loop_start()
        devices.append((sim, client, status_topic))
    print("[exemplos] %d camaras de exemplo -> %s:%d" % (len(devices), host, port))

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())

    while not stop.is_set():
        now = time.time()
        health = pi_health()
        for sim, client, _ in devices:
            payload = demo_sim.step(sim, now)
            payload.update(health)
            if client.is_connected():
                client.publish(sim["base"] + "/state", json.dumps(payload), qos=0, retain=True)
        stop.wait(demo_sim.STEP)

    # Paragem limpa: marcar todas como offline (o last will so atua em quedas)
    for sim, client, status_topic in devices:
        if client.is_connected():
            info = client.publish(status_topic, "offline", qos=1, retain=True)
            try:
                info.wait_for_publish(2)
            except TypeError:  # paho-mqtt 1.x sem timeout
                info.wait_for_publish()
        client.disconnect()
        client.loop_stop()
    print("[exemplos] parado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
