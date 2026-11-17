"""Vitrine SIM - Webserver HTTP no ESP32-S3 Supermini / MicroPython.
Simula uma vitrine expositora refrigerada (ver simulator.py).
"""
import gc
import json
import machine
import network
import socket
import time
from simulator import Showcase
from mqtt_pub import MQTTPub
from location import load as load_location
import netcfg
import config
import board

sim = Showcase()

# Causa do ultimo arranque (WDT = o watchdog reiniciou o ESP32 depois de um bloqueio)
_CAUSES = {getattr(machine, n): n.replace('_RESET', '').lower() for n in
           ('PWRON_RESET', 'HARD_RESET', 'WDT_RESET', 'DEEPSLEEP_RESET', 'SOFT_RESET') if hasattr(machine, n)}
RESET_CAUSE = _CAUSES.get(machine.reset_cause(), str(machine.reset_cause()))
print('Arranque: causa', RESET_CAUSE)

# Menos calor: CPU a 160 MHz (o simulador nao precisa de 240 MHz)
CPU_MHZ = getattr(config, 'CPU_MHZ', 160)
if CPU_MHZ:
    try:
        machine.freq(CPU_MHZ * 1000000)
    except Exception as e:
        print('CPU: freq nao alterada', e)
try:
    import esp32
except ImportError:
    esp32 = None


def health():
    """Temperatura do chip, sinal Wi-Fi e memoria livre (diagnostico de bloqueios)."""
    out = {'reset_cause': RESET_CAUSE, 'uptime_s': time.ticks_ms() // 1000,
           'cpu_mhz': machine.freq() // 1000000, 'mem_free': gc.mem_free()}
    try:
        out['mcu_temp_c'] = esp32.mcu_temperature()
    except Exception:
        pass
    try:
        out['ip'] = wlan.ifconfig()[0]
        out['ssid'] = active_net['ssid'] if active_net else None
        out['rssi'] = wlan.status('rssi')
        out['txpower'] = wlan.config('txpower')
    except Exception:
        pass
    return out
LOCATION, MQTT_TOPIC = load_location(config)
DEFAULT_MQTT = getattr(config, 'MQTT_HOST', None)
MQTT_HOST = None   # definido depois de ligar ao Wi-Fi (ou descoberto na rede)
MQTT_INTERVAL = max(1, getattr(config, 'MQTT_INTERVAL', 5))
mqtt = None
mqtt_next = time.ticks_ms()

# --- Bluetooth (configuracao de redes; mesmo protocolo do ColdRoom/Pico) ------
BLE_NAME = 'Vitrine-' + LOCATION['equipamento'].upper()
BLE_BOOT_S = getattr(config, 'BLE_BOOT_WINDOW_S', 180)   # janela apos arrancar
BLE_WINDOW_S = getattr(config, 'BLE_WINDOW_S', 300)      # sem Wi-Fi / botao BOOT
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
    # Sem rede: reiniciar e tentar de novo.
    # Os 5 s permitem interromper com Ctrl+C.
    print('Sem Wi-Fi (estado %d); a reiniciar em 5 s...' % wlan.status())
    time.sleep(5)
    machine.reset()
# Rede sem 'mqtt_host' (ex.: NOS ou adicionada por BLE sem --mqtt-host): descobre o broker na rede
MQTT_HOST = active_net.get('mqtt_host')
# Menos calor: potencia Wi-Fi reduzida (13 dBm) quando o sinal e bom; com sinal fraco fica no maximo
TXPOWER = getattr(config, 'WIFI_TXPOWER', 13)
try:
    rssi = wlan.status('rssi')
    if TXPOWER and rssi > -67:
        wlan.config(txpower=TXPOWER)
    print('Wi-Fi: RSSI %d dBm, potencia %s dBm' % (rssi, wlan.config('txpower')))
except Exception as e:
    print('Wi-Fi: potencia nao alterada', e)
print('Wi-Fi: %s, IP %s, broker %s' % (active_net['ssid'], wlan.ifconfig()[0], MQTT_HOST))
print('Vitrine SIM (%s) em http://%s:%d' % (board.NAME, wlan.ifconfig()[0], config.HTTP_PORT))

sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', config.HTTP_PORT))
sock.listen(2)

# Watchdog: se o ciclo principal parar mais de WDT_S segundos, o ESP32 reinicia sozinho
WDT_S = getattr(config, 'WDT_S', 30)
wdt = machine.WDT(timeout=WDT_S * 1000) if WDT_S else None
sock.settimeout(0.25)

try:
    ticks = time.ticks_ms()
except AttributeError:
    ticks = None


# --- MQTT (broker da rede ativa: mqtt_host da rede ou config.MQTT_HOST) ---
# Se o broker configurado nao responder, procura o anuncio do Raspberry Pi na rede.
MQTT_PORT = getattr(config, 'MQTT_PORT', 1883)
mqtt_fails = 0


def discover_broker(timeout_s=7):
    """Escuta o anuncio do Raspberry Pi (UDP 47830) e devolve (ip, porta) ou None."""
    port = getattr(config, 'DISCOVERY_PORT', 47830)
    if not port:
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', port))
        s.settimeout(1)
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_s * 1000:
            if 'wdt' in globals() and wdt:
                wdt.feed()
            try:
                data, addr = s.recvfrom(128)
            except OSError:
                continue
            if data.startswith(b'COLDROOM-BROKER'):
                try:
                    p = json.loads(data[16:]).get('port', 1883)
                except ValueError:
                    p = 1883
                return addr[0], p
    finally:
        s.close()
    return None


def mqtt_step():
    """Publica o estado de MQTT_INTERVAL em MQTT_INTERVAL segundos; em falha tenta de novo 15 s depois."""
    global mqtt, mqtt_next, MQTT_HOST, MQTT_PORT, mqtt_fails
    if time.ticks_diff(time.ticks_ms(), mqtt_next) < 0:
        return
    if not MQTT_HOST:   # rede sem broker configurado: procurar o anuncio do Pi
        found = discover_broker()
        if not found:
            mqtt_next = time.ticks_add(time.ticks_ms(), 15000)
            return
        MQTT_HOST, MQTT_PORT = found
        print('MQTT: broker descoberto em %s:%d' % found)
    try:
        if mqtt is None:
            client = MQTTPub(getattr(config, 'DEVICE_NAME', 'Vitrine-SIM'), MQTT_HOST,
                             MQTT_PORT,
                             getattr(config, 'MQTT_USER', None), getattr(config, 'MQTT_PASSWORD', None),
                             keepalive=max(30, MQTT_INTERVAL * 3))
            client.connect(will_topic=MQTT_TOPIC + '/status', will_msg='offline')
            client.publish(MQTT_TOPIC + '/status', 'online', retain=True)
            mqtt = client
            mqtt_fails = 0
            print('MQTT ligado a %s, topico %s/state' % (MQTT_HOST, MQTT_TOPIC))
        data = sim.snapshot()
        data.pop('history', None)
        data.pop('events', None)
        data['location'] = LOCATION
        data.update(health())
        mqtt.publish(MQTT_TOPIC + '/state', json.dumps(data), retain=True)
        mqtt_next = time.ticks_add(time.ticks_ms(), MQTT_INTERVAL * 1000)
    except Exception as e:
        print('MQTT erro:', e)
        if mqtt:
            mqtt.close()
        mqtt = None
        mqtt_fails += 1
        found = discover_broker() if mqtt_fails >= 2 else None
        if found and found[0] != MQTT_HOST:
            print('MQTT: broker descoberto em %s:%d (era %s)' % (found[0], found[1], MQTT_HOST))
            MQTT_HOST, MQTT_PORT = found
            mqtt_next = time.ticks_ms()
        else:
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
        data['mqtt'] = {'enabled': True, 'connected': mqtt is not None,
                        'host': MQTT_HOST, 'topic': MQTT_TOPIC}
        data['wifi'] = {'ssid': active_net['ssid'], 'ip': wlan.ifconfig()[0]}
        data['ble'] = {'name': BLE_NAME, 'active_s': ble.remaining_s() if ble else 0}
        data.update(health())
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
    if wdt:
        wdt.feed()
    ble_step()
    # Botao BOOT premido 1 s -> abre a janela BLE
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
