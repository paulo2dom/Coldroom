"""Verificacoes da dinamica da vitrine (correr no PC: py tests/test_simulator.py)."""
import os
import random
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from simulator import Showcase, HP_TRIP_BAR

random.seed(7)


def warm(s, secs=3600):
    for _ in range(secs):
        s.step(1)


def first_alarm(s, name, secs):
    for t in range(secs):
        s.step(1)
        if name in s.alarms():
            return t
    return None


# Funcionamento normal (loja aberta, trafego medio): temperatura controlada, sem alarmes
s = Showcase()
s.action({'action': 'schedule', 'value': 'open'})
lo, hi, alarms = 99, -99, set()
for t in range(8 * 3600):
    s.step(1)
    if t > 1800:
        lo, hi = min(lo, s.air), max(hi, s.air)
    alarms.update(s.alarms())
d = s.snapshot()
assert d['simulated'] and d['type'] == 'vitrine' and len(d['history']) > 2
assert 0.5 < lo and hi < s.target + 4, 'ar fora do controlo: %.1f..%.1f' % (lo, hi)
assert not alarms, alarms
assert d['door_openings'] > 100 and 20 <= d['duty_pct'] <= 95
assert d['haccp']['max'] < 5

# Horario automatico: as 07:20 a loja esta fechada e luzes apagadas; abre as 08:00
s = Showcase()
s.step(1)
assert not s.store_open and not s.lights
warm(s, 41 * 60)
assert s.store_open and s.lights and s.clock() == '08:01'

# Degelo por paragem: compressor parado, ventiladores ligados, dura entre 12 e 30 min
s = Showcase()
warm(s, 1800)
s.action({'action': 'defrost'})
dur = 0
while s.defrost and dur < 3600:
    assert not s.compressor and s.fans
    s.step(1)
    dur += 1
assert 12 * 60 <= dur <= 30 * 60, dur

# Condensador sujo -> pressostato de alta dispara; rearme so depois de limpar
s = Showcase()
s.action({'action': 'schedule', 'value': 'open'})
warm(s)
s.action({'action': 'fault', 'name': 'dirty_condenser', 'value': True})
assert first_alarm(s, 'ALTA PRESSAO (PRESSOSTATO)', 3600) is not None
assert s.trip and not s.compressor and s.discharge > HP_TRIP_BAR - 3
try:
    s.action({'action': 'reset'})
    raise AssertionError('rearme devia ser recusado com o condensador sujo')
except ValueError:
    pass
s.action({'action': 'fault', 'name': 'dirty_condenser', 'value': False})
warm(s, 600)
s.action({'action': 'reset'})
assert not s.trip

# Fuga de R290: aspiracao baixa, superaquecimento alto, temperatura sobe
s = Showcase()
s.action({'action': 'schedule', 'value': 'open'})
warm(s)
s.action({'action': 'fault', 'name': 'gas_leak', 'value': True})
assert first_alarm(s, 'TEMPERATURA ALTA', 5 * 3600) is not None
s.step(1)
assert s.superheat >= 15 or not s.compressor

# Porta mal fechada: o sensor diz "fechada" mas o compressor trabalha muito mais
s = Showcase()
s.action({'action': 'schedule', 'value': 'open'})
warm(s, 2 * 3600)
duty0 = s.duty
s.action({'action': 'fault', 'name': 'door_ajar', 'value': True})
warm(s, 2 * 3600)
assert 'PORTA ABERTA' not in s.alarms() and s.duty > duty0 + 0.15

# Resistencia anti-embaciamento avariada com humidade alta -> vidros embaciados
s = Showcase()
s.action({'action': 'humidity', 'value': 75})
s.action({'action': 'fault', 'name': 'heater_fault', 'value': True})
assert first_alarm(s, 'VIDROS EMBACIADOS', 1800) is not None

# Porta aberta manualmente > 2 min -> alarme
s = Showcase()
s.action({'action': 'door', 'index': 2, 'value': True})
assert first_alarm(s, 'PORTA ABERTA', 200) is not None
assert s.snapshot()['doors'][2]

# Falha de energia: tudo desligado, consumo zero
s = Showcase()
warm(s, 600)
s.action({'action': 'fault', 'name': 'power_cut', 'value': True})
s.step(1)
d = s.snapshot()
assert not d['compressor'] and not d['fans'] and not d['lights'] and d['power_kw'] == 0 and d['voltage'] == 0

# Comandos invalidos
for bad in ({'action': 'setpoint', 'value': 20}, {'action': 'door', 'index': 5, 'value': True},
            {'action': 'traffic', 'value': 9}, {'action': 'schedule', 'value': 'x'}, {'action': 'nada'}):
    try:
        Showcase().action(bad)
        raise AssertionError('devia recusar %s' % bad)
    except ValueError:
        pass

print('OK: controlo normal, horario, degelo por paragem, pressostato, fuga R290, porta mal fechada, '
      'vidros embaciados, porta aberta, falha de energia, validacao de comandos')
