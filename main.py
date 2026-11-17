"""ColdRoom SIM - Webserver HTTP em MicroPython (Raspberry Pi Pico W ou ESP32-S3)."""
import gc
import json
import machine
import network
import socket
import time
from simulator import ColdRoom
from mqtt_pub import MQTTPub
from location import load as load_location
import netcfg
import config
import board

sim = ColdRoom()
sim.device_label = board.NAME + ' / ColdRoom SIM'
LOCATION, MQTT_TOPIC = load_location(config)
DEFAULT_MQTT = getattr(config, 'MQTT_HOST', None)
MQTT_INTERVAL = max(1, getattr(config, 'MQTT_INTERVAL', 5))
mqtt = None
mqtt_next = time.ticks_ms()

# --- Bluetooth (configuracao de redes) ---------------------------------------
BLE_NAME = 'ColdRoom-' + LOCATION['equipamento'].upper()
BLE_BOOT_S = getattr(config, 'BLE_BOOT_WINDOW_S', 180)   # janela apos arrancar
BLE_WINDOW_S = getattr(config, 'BLE_WINDOW_S', 300)      # sem Wi-Fi / botao BOOT(SEL)
ble = None
reset_at = None
active_net = None
wlan = network.WLAN(network.STA_IF)


def ble_open(reason, secs):
    global ble
    try:
        if ble is None:
            from ble_setup import BLESetup
            ble = BLESetup(BLE_NAME)
        print('BLE (%s):' % reason, end=' ')
        ble.start(secs)
    except Exception as e:  # BLE nunca deve impedir o simulador de correr
        print('BLE indisponivel:', e)


def ble_command(c):
    global reset_at
    cmd = c.get('cmd')
    nets = netcfg.load(config)
    if cmd == 'status':
        return {'ok': True, 'device': board.NAME, 'name': BLE_NAME, 'topic': MQTT_TOPIC,
                'ssid': active_net['ssid'] if active_net else None,
                'ip': wlan.ifconfig()[0] if wlan.isconnected() else None,
                'mqtt_host': MQTT_HOST, 'mqtt_connected': mqtt is not None,
                'networks': len(nets), 'ble_s': ble.remaining_s()}
    if cmd == 'list':
        return {'ok': True, 'networks': netcfg.public(nets, DEFAULT_MQTT)}
    if cmd == 'add':
        netcfg.add(c.get('ssid'), c.get('password') or '', c.get('mqtt_host'))
        return {'ok': True, 'msg': 'Rede guardada; usa "apply" para reiniciar e aplicar'}
    if cmd == 'remove':
        netcfg.remove(c.get('ssid'), config)
        return {'ok': True, 'msg': 'Rede removida'}
    if cmd == 'apply':
        reset_at = time.ticks_add(time.ticks_ms(), 3000)
        return {'ok': True, 'msg': 'A reiniciar em 3 s'}
    return {'ok': False, 'error': 'comando desconhecido: %s' % cmd}


def ble_step():
    if ble is None:
        return
    c = ble.poll()
    if c is not None:
        try:
            r = ble_command(c)
        except Exception as e:
            r = {'ok': False, 'error': str(e)}
        ble.reply(r)
    board.led(ble.enabled)   # LED aceso = BLE ativo
    if reset_at is not None and time.ticks_diff(time.ticks_ms(), reset_at) >= 0:
        machine.reset()


# --- Wi-Fi: rede conhecida com melhor sinal; sem rede -> BLE e novas tentativas ---
wlan.active(True)
ble_open('arranque', BLE_BOOT_S)
active_net = netcfg.connect(wlan, netcfg.load(config))
if not active_net:
    ble_open('sem rede Wi-Fi conhecida', BLE_WINDOW_S)
    next_try = time.ticks_add(time.ticks_ms(), 30000)
    while ble is not None and ble.enabled and not active_net:
        ble_step()
        time.sleep(0.1)
        if time.ticks_diff(time.ticks_ms(), next_try) >= 0:
            active_net = netcfg.connect(wlan, netcfg.load(config))
            next_try = time.ticks_add(time.ticks_ms(), 30000)
if not active_net:
    # Sem rede (ou chip Wi-Fi bloqueado apos soft reset): so um reinicio completo resolve.
    # Os 5 s permitem interromper com Ctrl+C.
    print('Sem Wi-Fi (estado %d); a reiniciar em 5 s...' % wlan.status())
    time.sleep(5)
    machine.reset()
MQTT_HOST = active_net.get('mqtt_host') or DEFAULT_MQTT
print('Wi-Fi: %s, IP %s, broker %s' % (active_net['ssid'], wlan.ifconfig()[0], MQTT_HOST))
print('ColdRoom SIM (%s) em http://%s:%d' % (board.NAME, wlan.ifconfig()[0], config.HTTP_PORT))

sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', config.HTTP_PORT))
sock.listen(2)
sock.settimeout(0.25)

try:
    ticks = time.ticks_ms()
except AttributeError:
    ticks = None


# --- MQTT (broker da rede ativa: mqtt_host da rede ou config.MQTT_HOST) ---


def mqtt_step():
    """Publica o estado de MQTT_INTERVAL em MQTT_INTERVAL segundos; em falha tenta de novo 15 s depois."""
    global mqtt, mqtt_next
    if not MQTT_HOST or time.ticks_diff(time.ticks_ms(), mqtt_next) < 0:
        return
    try:
        if mqtt is None:
            client = MQTTPub(getattr(config, 'DEVICE_NAME', 'ColdRoom-SIM'), MQTT_HOST,
                             getattr(config, 'MQTT_PORT', 1883),
                             getattr(config, 'MQTT_USER', None), getattr(config, 'MQTT_PASSWORD', None),
                             keepalive=max(30, MQTT_INTERVAL * 3))
            client.connect(will_topic=MQTT_TOPIC + '/status', will_msg='offline')
            client.publish(MQTT_TOPIC + '/status', 'online', retain=True)
            mqtt = client
            print('MQTT ligado a %s, topico %s/state' % (MQTT_HOST, MQTT_TOPIC))
        data = sim.snapshot()
        data.pop('history', None)
        data.pop('events', None)
        data['location'] = LOCATION
        mqtt.publish(MQTT_TOPIC + '/state', json.dumps(data), retain=True)
        mqtt_next = time.ticks_add(time.ticks_ms(), MQTT_INTERVAL * 1000)
    except Exception as e:
        print('MQTT erro:', e)
        if mqtt:
            mqtt.close()
        mqtt = None
        mqtt_next = time.ticks_add(time.ticks_ms(), 15000)


def send(client, status, body, mime='application/json'):
    if isinstance(body, str):
        body = body.encode()
    head = ('HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
            'Cache-Control: no-store\r\nConnection: close\r\n\r\n' % (status, mime, len(body)))
    client.sendall(head.encode())
    client.sendall(body)


def serve(client):
    client.settimeout(2)
    request = b''
    while b'\r\n\r\n' not in request and len(request) < 4096:
        part = client.recv(1024)
        if not part:
            return
        request += part
    if b'\r\n\r\n' not in request:
        send(client, '400 Bad Request', '{"error":"cabecalho demasiado longo"}')
        return
    rawhead, rest = request.split(b'\r\n\r\n', 1)
    lines = rawhead.decode().split('\r\n')
    first = lines[0].split(' ')
    if len(first) < 2:
        return
    method, path = first[0], first[1].split('?')[0]
    if method == 'GET' and path in ('/', '/index.html'):
        try:
            with open('index.html', 'rb') as f:
                # Enviar em blocos para limitar uso de memoria
                length = f.seek(0, 2)
                f.seek(0)
                headers = ('HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n'
                           'Content-Length: %d\r\nCache-Control: no-store\r\n'
                           'Connection: close\r\n\r\n' % length)
                client.sendall(headers.encode())
                while True:
                    block = f.read(1024)
                    if not block:
                        break
                    client.sendall(block)
        except OSError:
            send(client, '404 Not Found', '{"error":"index.html em falta"}')
    elif method == 'GET' and path == '/api/state':
        data = sim.snapshot()
        data['location'] = LOCATION
        data['mqtt'] = {'enabled': bool(MQTT_HOST), 'connected': mqtt is not None,
                        'host': MQTT_HOST, 'topic': MQTT_TOPIC}
        data['wifi'] = {'ssid': active_net['ssid'], 'ip': wlan.ifconfig()[0]}
        data['ble'] = {'name': BLE_NAME, 'active_s': ble.remaining_s() if ble else 0}
        send(client, '200 OK', json.dumps(data))
    elif method == 'POST' and path == '/api/action':
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.lower().strip()] = value.strip()
        try:
            n = int(headers.get('content-length', '-1'))
            if n < 2 or n > 512:
                raise ValueError('Tamanho invalido')
            data = rest
            while len(data) < n:
                part = client.recv(min(512, n - len(data)))
                if not part:
                    raise ValueError('Pedido incompleto')
                data += part
            sim.action(json.loads(data[:n].decode()))
            send(client, '200 OK', '{"ok":true}')
        except (ValueError, KeyError, TypeError) as exc:
            send(client, '400 Bad Request', json.dumps({'error': str(exc)}))
    else:
        send(client, '404 Not Found', '{"error":"endpoint inexistente"}')


bootsel_since = None
while True:
    ble_step()
    # BOOTSEL (Pico) / BOOT (ESP32) premido 1 s -> abre a janela BLE
    if board.button():
        if bootsel_since is None:
            bootsel_since = time.ticks_ms()
        elif time.ticks_diff(time.ticks_ms(), bootsel_since) > 1000 and not (ble and ble.enabled):
            ble_open(board.BUTTON_NAME, BLE_WINDOW_S)
    else:
        bootsel_since = None
    now = time.ticks_ms()
    elapsed = min(2.0, time.ticks_diff(now, ticks) / 1000.0) if ticks is not None else 0.25
    ticks = now
    # Atualizar continuamente sem depender de pedidos HTTP
    n = min(40, max(1, int(elapsed * sim.speed) + 1))
    step_dt = elapsed * sim.speed / n
    for _ in range(n):
        sim.step(step_dt)
    mqtt_step()
    try:
        client, address = sock.accept()
    except OSError:
        continue
    try:
        serve(client)
    except Exception as e:
        print('Erro HTTP:', e)
    finally:
        client.close()
        gc.collect()
