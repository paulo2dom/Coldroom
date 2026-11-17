#!/usr/bin/env python3
"""
ColdRoom · Consola central
--------------------------
Recolhe o estado de vários equipamentos de frio (câmaras no Pico W, vitrine no ESP32-S3,
exemplos no Raspberry Pi) através do Mosquitto
e serve uma consola web em tempo real (Server-Sent Events).

Pensado para o Raspberry Pi Zero 2 W: só depende de paho-mqtt
(sudo apt install python3-paho-mqtt). Tudo o resto é biblioteca padrão.

Uso:
    python3 coldroom_console.py            # normal (usa config.py)
    python3 coldroom_console.py --demo 8   # sem broker: simula 8 câmaras
"""

import argparse
import base64
import json
import math
import os
import queue
import random
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "static", "index.html")


def cfg(name, default=None):
    return getattr(config, name, default)


# ---------------------------------------------------------------------------
# Formatação de nomes:  porto-boavista -> "Porto Boavista"
# ---------------------------------------------------------------------------
_LOWER_WORDS = {"de", "da", "do", "das", "dos", "e"}


def pretty(slug, level=None):
    if slug is None:
        return ""
    s = str(slug)
    if level in ("country", "device"):
        return s.upper()
    words = s.replace("_", "-").split("-")
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        if i > 0 and w.lower() in _LOWER_WORDS:
            out.append(w.lower())
        elif len(w) <= 3 and any(c.isdigit() for c in w):
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


# ---------------------------------------------------------------------------
# Normalização do payload — aceita várias grafias de chaves
# ---------------------------------------------------------------------------
def _get(d, path):
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def pick(d, *paths):
    for p in paths:
        v = _get(d, p)
        if v is not None:
            return v
    return None


def num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def boolish(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    if s in ("1", "true", "on", "ligado", "ligados", "aberta", "open", "ativo", "active", "running", "sim", "yes"):
        return True
    if s in ("0", "false", "off", "parado", "desligado", "desligados", "fechada", "closed", "inativo", "inactive", "stopped", "nao", "não", "no"):
        return False
    return None


def text(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "Normal" if v else "Falha"
    return str(v)


def normalize_alarms(raw):
    out = []
    if raw is None:
        return out
    if isinstance(raw, dict):
        raw = [dict(code=k, **(v if isinstance(v, dict) else {"text": str(v)})) for k, v in raw.items()]
    if not isinstance(raw, list):
        return out
    for i, a in enumerate(raw):
        if isinstance(a, str):
            out.append({"code": a, "text": a, "severity": "alarm"})
        elif isinstance(a, dict):
            if a.get("active") is False:
                continue
            code = str(a.get("code") or a.get("id") or a.get("name") or f"A{i+1}")
            out.append({
                "code": code,
                "text": str(a.get("text") or a.get("msg") or a.get("message") or a.get("description") or code),
                "severity": str(a.get("severity") or a.get("level") or "alarm").lower(),
            })
    return out


def normalize(p):
    """Converte o JSON publicado pelo equipamento num formato canónico."""
    n = _normalize(p)
    # Simulador ColdRoom (Pico W): payload plano, sem "mode" e com "trip" booleano
    trip = p.get("trip") if isinstance(p, dict) else None
    if n["comp_protection"] is None and isinstance(trip, bool):
        n["comp_protection"] = "DISPARADA" if trip else "Normal"
    # Tipo de equipamento e hardware (campo "device": "<hardware> / <simulador>")
    raw_type = str(p.get("type") or "").lower() if isinstance(p, dict) else ""
    n["kind"] = "vitrine" if raw_type == "vitrine" else "camara"
    dev_txt = p.get("device") if isinstance(p, dict) else None
    n["hardware"] = str(dev_txt).split(" / ")[0].strip() if dev_txt else None
    n["model"] = text(p.get("model")) if isinstance(p, dict) else None
    # Hardware: temperatura do chip, IP e Wi-Fi (Pico W, ESP32-S3 ou Raspberry Pi)
    wifi = p.get("wifi") if isinstance(p, dict) and isinstance(p.get("wifi"), dict) else {}
    n["mcu_temp"] = num(pick(p, "mcu_temp_c", "chip_temp", "cpu_temp"))
    n["ip"] = text(pick(p, "ip", "wifi.ip") or wifi.get("ip"))
    n["ssid"] = text(pick(p, "ssid", "wifi.ssid") or wifi.get("ssid"))
    n["rssi"] = num(pick(p, "rssi", "wifi.rssi"))
    n["dev_uptime_s"] = num(pick(p, "uptime_s"))
    n["reset_cause"] = text(pick(p, "reset_cause"))
    if n["kind"] == "vitrine":
        if n["mode"] is None and p.get("phase_ok") is False:
            n["mode"] = "SEM ENERGIA"
        elif n["mode"] is None and trip:
            n["mode"] = "PRESSOSTATO"
        n["vitrine"] = vitrine_extra(p)
    if n["mode"] is None and n["comp_on"] is not None:
        n["mode"] = ("DEGELO" if n["defrost"] else "PROTEÇÃO" if trip
                     else "REFRIGERAÇÃO" if n["comp_on"] else "STANDBY")
    return n


def vitrine_extra(p):
    """Campos próprios da vitrine expositora (Vitrine SIM / ESP32-S3)."""
    h = p.get("haccp") if isinstance(p.get("haccp"), dict) else {}
    doors = p.get("doors") if isinstance(p.get("doors"), list) else []
    faults = p.get("faults") if isinstance(p.get("faults"), dict) else {}
    return {
        "product": num(p.get("product")),
        "clock": text(p.get("clock")),
        "store_open": boolish(p.get("store_open")),
        "schedule": text(p.get("schedule")),
        "traffic": num(p.get("traffic")),
        "doors": [bool(d) for d in doors],
        "door_openings": num(p.get("door_openings")),
        "lights": boolish(p.get("lights")),
        "lights_fault": bool(faults.get("lights_fault")),
        "antifog_pct": num(p.get("antifog_pct")),
        "fog_pct": num(p.get("fog_pct")),
        "humidity": num(p.get("humidity")),
        "ambient": num(p.get("ambient")),
        "condenser": num(p.get("condenser")),
        "condenser_fan": boolish(p.get("condenser_fan")),
        "duty_pct": num(p.get("duty_pct")),
        "compressor_starts": num(p.get("compressor_starts")),
        "defrost_in_min": num(p.get("defrost_in_min")),
        "haccp_min": num(h.get("min")), "haccp_max": num(h.get("max")),
        "haccp_minutes_above": num(h.get("minutes_above")), "haccp_limit": num(h.get("limit")),
    }


def _normalize(p):
    return {
        "name": pick(p, "name", "device_name", "equipment", "title"),
        "mode": text(pick(p, "mode", "state", "status.mode", "estado")),
        "uptime_s": num(pick(p, "uptime_s", "uptime", "sim_time_s", "sim_seconds", "t_s")),
        "speed": num(pick(p, "speed", "sim_speed", "time_scale")),

        "t_room": num(pick(p, "temp.room", "temperatures.room", "room_temp", "temp_room", "temperature", "temp_camara", "t_camara", "room")),
        "t_setpoint": num(pick(p, "temp.setpoint", "temperatures.setpoint", "setpoint", "sp", "target")),
        "t_supply": num(pick(p, "temp.supply", "temperatures.supply", "supply_air", "supply_temp", "t_insuflado", "ar_insuflado", "discharge_air")),
        "t_return": num(pick(p, "temp.return", "temperatures.return", "return_air", "return_temp", "t_retorno", "ar_retorno")),
        "t_evap": num(pick(p, "temp.evap", "temperatures.evaporator", "evap_temp", "evaporator_temp", "t_evaporador", "coil_temp", "evaporator")),

        "comp_on": boolish(pick(p, "compressor.on", "compressor.running", "compressor_on", "compressor.state", "compressor")),
        "comp_load": num(pick(p, "compressor.load", "compressor.capacity", "compressor_load", "compressor_pct")),
        "comp_protection": text(pick(p, "compressor.protection", "compressor_protection", "status.compressor_protection")),
        "comp_hours": num(pick(p, "compressor.hours", "compressor_hours", "hours.compressor")),

        "fans_on": boolish(pick(p, "fans.on", "fans.running", "fans_on", "fans.state", "fans")),
        "fans_hours": num(pick(p, "fans.hours", "fans_hours", "fan_hours", "hours.fans")),

        "eev_open": num(pick(p, "eev.opening", "eev.open", "eev_opening", "eev_pct", "expansion_pct", "eev")),
        "defrost": boolish(pick(p, "defrost.active", "defrost_active", "defrost.state", "defrost")),
        "door_open": boolish(pick(p, "door.open", "door_open", "door.state", "door")),

        "p_suction": num(pick(p, "pressure.suction", "pressures.suction", "suction_pressure", "p_suction", "suction_bar")),
        "p_discharge": num(pick(p, "pressure.discharge", "pressures.discharge", "discharge_pressure", "p_discharge", "discharge_bar")),
        "superheat": num(pick(p, "superheat", "pressure.superheat", "sh")),
        "subcooling": num(pick(p, "subcooling", "pressure.subcooling", "sc")),

        "voltage": num(pick(p, "electrical.voltage", "power.voltage", "voltage", "v")),
        "current": num(pick(p, "electrical.current", "power.current", "current", "a")),
        "power_kw": num(pick(p, "electrical.power_kw", "power.kw", "power_kw", "kw")),
        "energy_kwh": num(pick(p, "electrical.energy_kwh", "power.energy_kwh", "energy_kwh", "kwh")),

        "phase_monitor": text(pick(p, "status.phase_monitor", "phase_monitor", "phases", "phase_ok")),
        "comp_oil": text(pick(p, "status.compressor_oil", "compressor_oil", "oil", "oil_ok")),
        "refrigerant": text(pick(p, "status.refrigerant", "refrigerant", "refrigerant_ok")),

        "alarms": normalize_alarms(pick(p, "alarms", "active_alarms", "alarmes")),
    }


# ---------------------------------------------------------------------------
# Estado central
# ---------------------------------------------------------------------------
class Hub:
    def __init__(self):
        self.lock = threading.RLock()
        self.devices = {}               # key -> dict
        self.events = deque(maxlen=int(cfg("EVENT_LOG_SIZE", 300)))
        self.clients = []               # filas SSE
        self.broker = {"state": "disabled", "host": None, "since": time.time(), "error": None}
        self.started = time.time()
        self.msg_total = 0

    # ---------- SSE ----------
    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def broadcast(self, kind, data):
        msg = f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
        with self.lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    self.clients.remove(q)

    # ---------- broker ----------
    def set_broker(self, state, error=None):
        with self.lock:
            if self.broker["state"] != state:
                self.broker["since"] = time.time()
                prev = self.broker["state"]
                self.broker["state"] = state
                self.broker["error"] = error
                if prev != "disabled" or state != "disabled":
                    self.log_event(None, "broker", "info" if state in ("connected", "demo") else "alarm",
                                   {"connected": "Ligação ao broker MQTT estabelecida",
                                    "disconnected": "Ligação ao broker MQTT perdida",
                                    "demo": "Modo de demonstração ativo"}.get(state, state), state != "disconnected")
            self.broker["error"] = error
            self.broadcast("broker", self.broker)

    # ---------- eventos ----------
    def log_event(self, dev, code, severity, msg, cleared):
        ev = {
            "ts": time.time(),
            "device": dev["key"] if dev else None,
            "label": (f'{dev["device_label"]} · {dev["loc"]["store"]}' if dev else "Consola"),
            "code": code,
            "severity": severity,
            "text": msg,
            "cleared": cleared,
        }
        self.events.appendleft(ev)
        self.broadcast("event", ev)

    # ---------- mensagens ----------
    def handle_message(self, topic, payload):
        parts = [p for p in topic.split("/") if p]
        if len(parts) < 2:
            return
        kind = parts[-1].lower()
        key = "/".join(parts[:-1])
        segs = parts[:-1]
        # pais / zona / loja / local / equipamento (completa à esquerda se faltar)
        while len(segs) < 5:
            segs.insert(0, "")
        country, zone, store, place, device = segs[-5:]

        now = time.time()
        with self.lock:
            self.msg_total += 1
            dev = self.devices.get(key)
            if dev is None:
                dev = {
                    "key": key,
                    "topic": f"{key}/state",
                    "slug": {"country": country, "zone": zone, "store": store, "place": place, "device": device},
                    "loc": {"country": pretty(country, "country"), "zone": pretty(zone), "store": pretty(store),
                            "place": pretty(place), "device": pretty(device, "device")},
                    "device_label": pretty(device, "device"),
                    "name": f"Câmara frigorífica {pretty(device, 'device')}",
                    "first_seen": now, "last_seen": None, "msg_count": 0,
                    "lwt": None, "data": {}, "raw": None,
                    "history": deque(maxlen=int(cfg("HISTORY_POINTS", 720))),
                    "last_hist": 0, "alarms": [], "alarm_keys": set(),
                    "temp_high_since": None, "comm": "waiting",
                }
                self.devices[key] = dev

            if kind in ("status", "availability", "lwt"):
                val = payload.decode("utf-8", "replace").strip().lower()
                try:
                    j = json.loads(val)
                    if isinstance(j, dict):
                        val = str(j.get("status") or j.get("state") or "").lower()
                except ValueError:
                    pass
                dev["lwt"] = "online" if val in ("online", "1", "true", "connected") else "offline"
                self._evaluate(dev, now)
                self.broadcast("device", self.summary(dev))
                return

            if kind != "state":
                return

            try:
                p = json.loads(payload.decode("utf-8", "replace"))
                if not isinstance(p, dict):
                    raise ValueError("payload não é um objeto JSON")
            except ValueError as e:
                dev["parse_error"] = str(e)
                return

            dev.pop("parse_error", None)
            dev["raw"] = p
            d = normalize(p)
            dev["data"] = d
            if d.get("name"):
                dev["name"] = str(d["name"])
            else:
                dev["name"] = ("Vitrine expositora " if d.get("kind") == "vitrine"
                               else "Câmara frigorífica ") + dev["device_label"]
            dev["last_seen"] = now
            dev["msg_count"] += 1
            if dev["lwt"] == "offline":
                dev["lwt"] = "online"

            point = None
            if now - dev["last_hist"] >= float(cfg("HISTORY_INTERVAL_S", 10)):
                dev["last_hist"] = now
                point = [round(now), d["t_room"], d["t_supply"], d["t_return"], d["t_setpoint"], d["t_evap"],
                         (d.get("vitrine") or {}).get("product")]
                dev["history"].append(point)

            self._evaluate(dev, now)
            s = self.summary(dev)
            if point:
                s["point"] = point
            self.broadcast("device", s)

    # ---------- alarmes ----------
    def _evaluate(self, dev, now):
        stale = float(cfg("STALE_AFTER_S", 60))
        if dev["last_seen"] is None:
            comm = "waiting"
        elif dev["lwt"] == "offline":
            comm = "offline"
        elif now - dev["last_seen"] > stale:
            comm = "stale"
        else:
            comm = "online"
        dev["comm"] = comm

        alarms = list(dev["data"].get("alarms") or []) if comm == "online" else []
        if comm in ("offline", "stale"):
            alarms.append({"code": "COMM", "severity": "critical", "source": "consola",
                           "text": "Equipamento offline (LWT)" if comm == "offline"
                           else f"Sem comunicação há mais de {int(stale)} s"})

        delta = cfg("TEMP_HIGH_DELTA", None)
        d = dev["data"]
        if delta is not None and comm == "online" and d.get("t_room") is not None and d.get("t_setpoint") is not None \
                and not d.get("defrost"):
            if d["t_room"] > d["t_setpoint"] + float(delta):
                dev["temp_high_since"] = dev["temp_high_since"] or now
                if now - dev["temp_high_since"] >= float(cfg("TEMP_HIGH_DELAY_S", 300)) \
                        and not any(a["code"] in ("HT", "TEMP_HIGH") for a in alarms):
                    alarms.append({"code": "TEMP_HIGH", "severity": "critical", "source": "consola",
                                   "text": f"Temperatura acima do setpoint +{float(delta):.1f} °C"})
            else:
                dev["temp_high_since"] = None
        elif comm == "online":
            dev["temp_high_since"] = None

        keys = {a["code"] for a in alarms}
        old = dev["alarm_keys"]
        if dev["last_seen"] is not None or comm != "waiting":
            for a in alarms:
                if a["code"] not in old:
                    self.log_event(dev, a["code"], a.get("severity", "alarm"), a["text"], False)
            for a in dev["alarms"]:
                if a["code"] not in keys:
                    self.log_event(dev, a["code"], "info", f'{a["text"]} — reposto', True)
        dev["alarms"] = alarms
        dev["alarm_keys"] = keys

    def tick(self):
        """Corre a cada 2 s: deteta câmaras sem comunicação e alarmes temporizados."""
        now = time.time()
        with self.lock:
            for dev in self.devices.values():
                before = (dev["comm"], tuple(sorted(dev["alarm_keys"])))
                self._evaluate(dev, now)
                if before != (dev["comm"], tuple(sorted(dev["alarm_keys"]))):
                    self.broadcast("device", self.summary(dev))
        self.broadcast("tick", {"now": now})

    # ---------- serialização ----------
    def summary(self, dev, spark=False):
        s = {k: dev[k] for k in ("key", "topic", "slug", "loc", "device_label", "name", "first_seen",
                                 "last_seen", "msg_count", "lwt", "comm", "alarms", "data")}
        if dev.get("parse_error"):
            s["parse_error"] = dev["parse_error"]
        if spark:
            s["spark"] = [[h[0], h[1]] for h in list(dev["history"])[-90:]]
        return s

    def snapshot(self):
        with self.lock:
            return {
                "console": {"name": cfg("CONSOLE_NAME", "Consola central"), "started": self.started,
                            "now": time.time(), "stale_after": cfg("STALE_AFTER_S", 60),
                            "history_interval": cfg("HISTORY_INTERVAL_S", 10),
                            "topics": cfg("MQTT_TOPICS", []), "msg_total": self.msg_total,
                            "temp_high_delta": cfg("TEMP_HIGH_DELTA", None),
                            "temp_high_delay": cfg("TEMP_HIGH_DELAY_S", 300),
                            "http_auth": bool(cfg("HTTP_USER")), "mqtt_tls": bool(cfg("MQTT_TLS", False))},
                "broker": self.broker,
                "devices": [self.summary(d, spark=True) for d in self.devices.values()],
                "events": list(self.events)[:100],
            }

    def detail(self, key):
        with self.lock:
            dev = self.devices.get(key)
            if not dev:
                return None
            s = self.summary(dev)
            s["history"] = list(dev["history"])
            s["raw"] = dev["raw"]
            s["events"] = [e for e in self.events if e["device"] == key][:50]
            return s


HUB = Hub()


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
def start_mqtt():
    host = cfg("MQTT_HOST", None)
    if not host:
        HUB.set_broker("disabled")
        print("[mqtt] MQTT_HOST não definido — MQTT desativado")
        return
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        HUB.set_broker("disconnected", "paho-mqtt não instalado (sudo apt install python3-paho-mqtt)")
        print("[mqtt] ERRO: paho-mqtt não instalado")
        return

    HUB.broker["host"] = f"{host}:{cfg('MQTT_PORT', 1883)}"
    try:  # paho-mqtt 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg("MQTT_CLIENT_ID", "coldroom-console"))
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=cfg("MQTT_CLIENT_ID", "coldroom-console"))

    if cfg("MQTT_USER"):
        client.username_pw_set(cfg("MQTT_USER"), cfg("MQTT_PASSWORD"))
    if cfg("MQTT_TLS", False):
        client.tls_set(ca_certs=cfg("MQTT_CA_FILE"))

    def on_connect(c, userdata, flags, rc, *args):
        code = getattr(rc, "value", rc)
        if code == 0:
            for t in cfg("MQTT_TOPICS", ["+/+/+/+/+/state"]):
                c.subscribe(t, qos=0)
            HUB.set_broker("connected")
            print(f"[mqtt] ligado a {HUB.broker['host']}")
        else:
            HUB.set_broker("disconnected", f"recusado (rc={rc})")

    def on_disconnect(c, userdata, *args):
        HUB.set_broker("disconnected", "ligação perdida")
        print("[mqtt] ligação perdida — a tentar novamente")

    def on_message(c, userdata, msg):
        try:
            HUB.handle_message(msg.topic, msg.payload)
        except Exception as e:  # nunca deixar cair o loop do paho
            print(f"[mqtt] erro a processar {msg.topic}: {e}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=15)
    HUB.set_broker("disconnected", "a ligar…")
    client.connect_async(host, int(cfg("MQTT_PORT", 1883)), keepalive=int(cfg("MQTT_KEEPALIVE", 15)))
    client.loop_start()


# ---------------------------------------------------------------------------
# Simulador de demonstração (sem broker) — útil para testar a consola
# ---------------------------------------------------------------------------
DEMO_SITES = [
    ("pt", "norte", "porto-boavista", "talho", 2.0),
    ("pt", "norte", "porto-boavista", "peixaria", 0.0),
    ("pt", "norte", "porto-boavista", "congelados", -20.0),
    ("pt", "norte", "braga-centro", "talho", 2.0),
    ("pt", "norte", "vila-nova-de-gaia", "lacticinios", 4.0),
    ("pt", "centro", "coimbra-baixa", "talho", 2.0),
    ("pt", "sul", "lisboa-alvalade", "frutas-e-legumes", 6.0),
    ("pt", "sul", "lisboa-alvalade", "congelados", -18.0),
    ("pt", "sul", "faro-gambelas", "peixaria", 0.0),
    ("es", "galicia", "vigo-centro", "carniceria", 2.0),
]


def start_demo(n):
    """Modo --demo: camaras simuladas injetadas diretamente, sem broker."""
    import demo_sim
    HUB.set_broker("demo")
    sims = []
    for i in range(n):
        c, z, s, l, sp = DEMO_SITES[i % len(DEMO_SITES)]
        idx = i // len(DEMO_SITES) + 1
        sims.append(demo_sim.new_sim(f"{c}/{z}/{s}/{l}/cf-{idx:02d}", sp, fault=i == 3, silent=i == 5))

    def loop():
        while True:
            now = time.time()
            for sim in sims:
                payload = demo_sim.step(sim, now)
                if sim["silent"] and now - sim["start"] > 40:
                    continue  # simula equipamento que deixa de comunicar
                HUB.handle_message(sim["base"] + "/state", json.dumps(payload).encode())
            time.sleep(demo_sim.STEP)

    threading.Thread(target=loop, daemon=True, name="demo").start()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ColdRoomConsole/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # silencioso (o SD card agradece)

    def _auth_ok(self):
        user = cfg("HTTP_USER")
        if not user:
            return True
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(hdr[6:]).decode().partition(":")
                if u == user and p == (cfg("HTTP_PASSWORD") or ""):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ColdRoom"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":"))
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth_ok():
            return
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                with open(INDEX_FILE, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "index.html em falta", "text/plain; charset=utf-8")
        elif u.path == "/api/state":
            self._send(200, HUB.snapshot())
        elif u.path == "/api/device":
            key = parse_qs(u.query).get("id", [""])[0]
            d = HUB.detail(key)
            self._send(200 if d else 404, d or {"error": "câmara desconhecida"})
        elif u.path == "/events":
            self._sse()
        elif u.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, {"error": "não encontrado"})

    def _sse(self):
        q = HUB.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    msg = ": ping\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            HUB.unsubscribe(q)
            self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def ticker():
    while True:
        time.sleep(2)
        try:
            HUB.tick()
        except Exception as e:
            print(f"[tick] erro: {e}")


def start_broker_beacon():
    """Anuncia o broker na rede local (UDP broadcast de 5 em 5 s).

    O Pico e o ESP32 escutam este anuncio quando nao conseguem ligar ao broker
    configurado (ex.: noutra rede Wi-Fi, onde o Pi tem outro IP) e usam o IP de
    quem o enviou. Mensagem: COLDROOM-BROKER {"port": 1883}
    """
    port = int(cfg("DISCOVERY_PORT", 47830))
    if not port:
        return
    msg = ("COLDROOM-BROKER " + json.dumps({"port": int(cfg("MQTT_PORT", 1883))})).encode()

    def loop():
        import socket
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(msg, ("255.255.255.255", port))
                s.close()
            except OSError:
                pass   # sem rede: tenta outra vez daqui a 5 s
            time.sleep(5)
    threading.Thread(target=loop, daemon=True, name="beacon").start()
    print(f"[beacon] anuncio do broker em UDP {port}")


def main():
    ap = argparse.ArgumentParser(description="ColdRoom · Consola central")
    ap.add_argument("--demo", type=int, nargs="?", const=8, metavar="N",
                    help="simula N câmaras sem broker MQTT (predefinição 8)")
    ap.add_argument("--port", type=int, default=None, help="porta HTTP (sobrepõe config.py)")
    args = ap.parse_args()

    if args.demo:
        start_demo(args.demo)
    else:
        start_mqtt()  # as camaras de exemplo chegam pelo broker (servico coldroom-examples)
        start_broker_beacon()
    threading.Thread(target=ticker, daemon=True, name="ticker").start()

    host, port = cfg("HTTP_HOST", "0.0.0.0"), args.port or int(cfg("HTTP_PORT", 8080))
    srv = Server((host, port), Handler)
    print(f"[http] consola em http://{host}:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
