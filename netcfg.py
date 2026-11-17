"""Redes Wi-Fi conhecidas do Pico W.

Origem das redes:
  - config.py: WIFI_NETWORKS (predefinidas, editadas no PC)
  - networks.json: redes adicionadas/removidas por Bluetooth (BLE)
Cada rede: {'ssid': ..., 'password': ..., 'mqtt_host': ...}. O mqtt_host e o IP
do Raspberry Pi (broker) NESSA rede; se faltar (None), o broker e descoberto
automaticamente pelo anuncio UDP que o Pi envia (porta 47830).
"""
import json
import time

FILE = 'networks.json'


def _defaults(config):
    nets = list(getattr(config, 'WIFI_NETWORKS', None) or [])
    if not nets and getattr(config, 'WIFI_SSID', None):
        nets = [{'ssid': config.WIFI_SSID, 'password': getattr(config, 'WIFI_PASSWORD', ''),
                 'mqtt_host': getattr(config, 'MQTT_HOST', None)}]
    return [dict(n) for n in nets if n.get('ssid')]


def _read_file():
    try:
        with open(FILE) as f:
            data = json.load(f)
        return list(data.get('networks', [])), list(data.get('removed', []))
    except (OSError, ValueError):
        return [], []


def _write_file(nets, removed):
    with open(FILE, 'w') as f:
        json.dump({'networks': nets, 'removed': removed}, f)


def load(config):
    """Lista final de redes. As do networks.json sobrepoem as do config.py com o mesmo SSID."""
    saved, removed = _read_file()
    out = {}
    for n in _defaults(config):
        if n['ssid'] not in removed:
            n['source'] = 'config'
            out[n['ssid']] = n
    for n in saved:
        n = dict(n)
        n['source'] = 'ble'
        out[n['ssid']] = n
    return list(out.values())


def public(nets, default_mqtt=None):
    """Lista sem passwords, para enviar por BLE."""
    return [{'ssid': n['ssid'], 'mqtt_host': n.get('mqtt_host') or 'auto (anuncio do Pi)',
             'source': n.get('source', '?')} for n in nets]


def add(ssid, password, mqtt_host=None):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
        raise ValueError('SSID invalido (1 a 32 bytes)')
    if not isinstance(password, str) or not (len(password) == 0 or 8 <= len(password.encode()) <= 63):
        raise ValueError('Password invalida (8 a 63 caracteres, ou vazia para rede aberta)')
    if mqtt_host is not None and (not isinstance(mqtt_host, str) or len(mqtt_host) > 64):
        raise ValueError('mqtt_host invalido')
    saved, removed = _read_file()
    saved = [n for n in saved if n.get('ssid') != ssid]
    saved.append({'ssid': ssid, 'password': password, 'mqtt_host': mqtt_host or None})
    removed = [s for s in removed if s != ssid]
    _write_file(saved, removed)


def remove(ssid, config):
    saved, removed = _read_file()
    known = [n['ssid'] for n in load(config)]
    if ssid not in known:
        raise ValueError('Rede desconhecida: %s' % ssid)
    saved = [n for n in saved if n.get('ssid') != ssid]
    if ssid in [n['ssid'] for n in _defaults(config)] and ssid not in removed:
        removed.append(ssid)  # esconder a rede do config.py
    _write_file(saved, removed)


def connect(wlan, nets, timeout_s=15):
    """Procura as redes conhecidas visiveis e liga-se a de melhor sinal.
    Devolve a rede usada (dict) ou None."""
    if not nets:
        return None
    try:
        wlan.disconnect()   # ESP32: o scan falha se ainda estiver a tentar ligar
    except OSError:
        pass
    try:
        seen = {}
        for r in wlan.scan():
            ssid = r[0].decode('utf-8', 'replace')
            if ssid:
                seen[ssid] = max(seen.get(ssid, -999), r[3])
    except OSError as e:
        print('Wi-Fi: scan falhou', e)
        return None
    print('Wi-Fi: %d redes visiveis' % len(seen))
    candidates = sorted([n for n in nets if n['ssid'] in seen], key=lambda n: -seen[n['ssid']])
    for n in candidates:
        print('Wi-Fi: a ligar a %s (%d dBm)' % (n['ssid'], seen[n['ssid']]))
        try:
            wlan.disconnect()
        except OSError:
            pass
        wlan.connect(n['ssid'], n.get('password') or '')
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_s * 1000:
            if wlan.isconnected():
                return n
            st = wlan.status()
            if st < 0 or 200 <= st < 1000:  # falha (Pico: <0; ESP32: 200..212)
                break
            time.sleep(0.25)
        print('Wi-Fi: falhou %s (estado %d)' % (n['ssid'], wlan.status()))
    return None
