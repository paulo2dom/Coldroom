"""Modelo de camaras frigorificas simuladas (exemplos e modo --demo).

Gera, a cada passo, um payload JSON no MESMO formato que o Pico W (ColdRoom SIM)
publica em .../state, para que todos os equipamentos usem o mesmo esquema.
Usado por:
  - coldroom_examples.py  -> publica as camaras de exemplo no Mosquitto
  - coldroom_console.py --demo -> injeta camaras simuladas sem broker
Valores ficticios, apenas para demonstracao.
"""
import random
import time
import zlib

# Contadores (energia, horas) consistentes entre reinicios: valor base fixo por
# camara (derivado do topico) + taxa media desde esta data de referencia.
EPOCH = 1735689600      # 2025-01-01 00:00 UTC
DUTY = 0.45             # fracao media do tempo com o compressor ligado
AVG_KW = 1.1            # potencia media (kW)
DOOR_ALARM_S = 60       # porta aberta ha mais de N s -> alarme
STEP = 5                # segundos entre passos


def new_sim(base_topic, sp, fault=False, silent=False, example=False, ambient=24.0):
    """base_topic: 'pais/zona/loja/local/equipamento' (sem /state)."""
    base_topic = base_topic.strip("/")
    if base_topic.endswith("/state"):
        base_topic = base_topic[:-len("/state")]
    rng = random.Random(zlib.crc32(base_topic.encode()))   # sempre os mesmos valores base por camara
    hours = max(0.0, (time.time() - EPOCH) / 3600)
    return {
        "base": base_topic, "sp": float(sp), "ambient": ambient,
        "t": float(sp) + (4.6 if fault else random.uniform(-0.5, 1.0)),
        "comp": False, "defrost_left": 0, "door_left": 0, "door_open_s": 0,
        "energy": rng.uniform(500, 3000) + AVG_KW * hours,
        "ch": rng.uniform(1000, 6000) + DUTY * hours,
        "fh": rng.uniform(2000, 9000) + 0.95 * hours,
        "start": time.time(),
        "fault": fault, "silent": silent, "example": example,
        "next_defrost": time.time() + random.uniform(300, 3600),
    }


def sat_pressure(t):
    """Pressao de saturacao aproximada (bar relativos) de um R404A a t degC.
    Ajuste quadratico a -30, -10 e 0 degC; suficiente para uma simulacao didatica."""
    return max(0.1, 5.1 + 0.1963 * t + 0.002033 * t * t)


def location(base_topic):
    keys = ("pais", "zona", "loja", "local", "equipamento")
    parts = base_topic.split("/")
    return dict(zip(keys, parts)) if len(parts) == 5 else None


def step(s, now=None):
    """Avanca STEP segundos e devolve o payload (dict, formato Pico W)."""
    now = time.time() if now is None else now
    sp = s["sp"]
    err = s["t"] - sp

    # Degelo: 10 min, a cada 2-4 h
    if s["defrost_left"] <= 0 and now > s["next_defrost"]:
        s["defrost_left"] = 600 // STEP
        s["next_defrost"] = now + random.uniform(2 * 3600, 4 * 3600)
    defrost = s["defrost_left"] > 0
    if defrost:
        s["defrost_left"] -= 1

    # Porta: ~1 abertura a cada 20 min; 30 % ficam abertas mais de DOOR_ALARM_S
    if s["door_left"] <= 0 and random.random() < 0.004:
        long_open = random.random() < 0.3
        secs = random.uniform(DOOR_ALARM_S + 5, 180) if long_open else random.uniform(10, 40)
        s["door_left"] = max(1, int(secs // STEP))
    door = s["door_left"] > 0
    if door:
        s["door_left"] -= 1
        s["door_open_s"] += STEP
    else:
        s["door_open_s"] = 0

    # Compressor com histerese (desligado em degelo)
    if defrost:
        s["comp"] = False
    elif err > 1.0:
        s["comp"] = True
    elif err < -0.8:
        s["comp"] = False
    load = max(40.0, min(100.0, 60 + err * 20 + random.uniform(-3, 3))) if s["comp"] else 0.0

    # Balanco termico (por passo de 5 s): ganho ~0,1-0,2 degC/min, frio ate ~0,6 degC/min
    cooling = (0.05 * load / 100) if (s["comp"] and not s["fault"]) else 0.0
    s["t"] += random.uniform(0.008, 0.016) + (0.04 if door else 0) + (0.008 if defrost else 0) - cooling

    # Valores derivados
    t = s["t"]
    evap = (t + 6) if defrost else (t - 8 if s["comp"] else t - 1)
    suction = sat_pressure(evap) + random.uniform(-0.05, 0.05)
    discharge = ((16.5 + (load - 80) * 0.02) if s["comp"] else 10.5) + random.uniform(-0.1, 0.1)
    kw = ((0.5 + 2.2 * load / 100) if s["comp"] else 0) + (0 if defrost else 0.18) + (2.0 if defrost else 0)
    s["energy"] += kw * STEP / 3600
    if s["comp"]:
        s["ch"] += STEP / 3600
    if not defrost:
        s["fh"] += STEP / 3600
    volts = 400 + random.uniform(-3, 3)

    alarms = []
    if door and s["door_open_s"] > DOOR_ALARM_S:
        alarms.append("PORTA ABERTA HA MAIS DE %d s" % DOOR_ALARM_S)
    if s["fault"]:
        alarms.append("REFRIGERANTE BAIXO")

    device = s["base"].split("/")[-1].upper()
    payload = {
        "simulated": True,
        "example": s["example"],
        "name": "Câmara frigorífica %s%s" % (device, " (exemplo)" if s["example"] else ""),
        "device": "Raspberry Pi / ColdRoom exemplo" if s["example"] else "Raspberry Pi / ColdRoom demo",
        "sim_seconds": int(now - s["start"]), "speed": 1,
        "target": sp, "ambient": s["ambient"],
        "room": round(t, 2),
        "discharge_air": round(t - (1.5 + load * 0.02) if s["comp"] else t + (0.4 if defrost else -0.1), 2),
        "return_air": round(t + (0.8 if door else 0.3), 2),
        "evaporator": round(evap, 2),
        "suction_bar": round(suction, 2), "discharge_bar": round(discharge, 2),
        "superheat": round(5.5 + (4 if s["fault"] else 0) + random.uniform(-0.6, 0.6), 2),
        "subcooling": round(max(0.0, 5.0 - (3.5 if s["fault"] else 0) + random.uniform(-0.4, 0.4)), 2),
        "compressor": s["comp"], "compressor_pct": round(load),
        "fans": not defrost,
        "expansion_pct": round(max(20, min(85, 35 + err * 8 + random.uniform(-2, 2)))) if s["comp"] else 0,
        "defrost": defrost, "door": door,
        "phase_ok": True, "voltage": round(volts, 1),
        "current": round(kw * 1000 / (1.732 * volts * 0.85), 2),
        "power_kw": round(kw, 2), "energy_kwh": round(s["energy"], 2),
        "compressor_hours": round(s["ch"], 1), "fan_hours": round(s["fh"], 1),
        "oil_ok": True, "refrigerant_ok": not s["fault"],
        "phase_fault": False, "oil_fault": False, "low_refrigerant": s["fault"], "hp_fault": False,
        "trip": False, "alarms": alarms,
    }
    loc = location(s["base"])
    if loc:
        payload["location"] = loc
    return payload
