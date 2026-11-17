import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from simulator import ColdRoom
s=ColdRoom()
for _ in range(150):s.step(1)
a=s.snapshot()
assert a['simulated'] and len(a['history'])>2 and a['sim_seconds']==150
assert a['compressor'] and a['compressor_pct']>0
s.action({'action':'fault','name':'phase_fault','value':True})
s.step(1)
assert s.trip and not s.compressor and 'FALHA DE FASE' in s.snapshot()['alarms']
try:
    s.action({'action':'reset'})
    raise AssertionError('Expected reset rejection')
except ValueError:pass
s.action({'action':'fault','name':'phase_fault','value':False})
s.action({'action':'reset'})
assert not s.trip
s.action({'action':'door','value':True})
assert s.snapshot()['door']
s.action({'action':'defrost'})
assert s.defrost
s.action({'action':'speed','value':20})
assert s.speed==20
# Aspiracao nunca negativa em congelacao (com e sem refrigerante baixo)
s=ColdRoom()
s.action({'action':'setpoint','value':-18})
s.action({'action':'fault','name':'low_refrigerant','value':True})
low=99
for _ in range(7200):
    s.step(1); low=min(low,s.suction)
assert low>=0.2, 'aspiracao negativa: %.2f' % low
# Falha de fase durante degelo: sem tensao, a resistencia nao consome nem aquece
s=ColdRoom()
for _ in range(600):s.step(1)
s.action({'action':'defrost'})
for _ in range(30):s.step(1)
s.action({'action':'fault','name':'phase_fault','value':True})
t0=s.room
for _ in range(60):s.step(1)
a=s.snapshot()
assert a['defrost'] and a['voltage']==0 and a['current']==0 and a['power_kw']==0, a['power_kw']
assert s.room<t0+0.5, 'camara aqueceu com resistencia sem tensao'
# Alarmes de temperatura: sem falsos alarmes num dia normal; ALTA quando o compressor para
s=ColdRoom()
seen=set()
for _ in range(24*3600):
    s.step(1); seen.update(s.snapshot()['alarms'])
assert not seen, seen
s.action({'action':'fault','name':'phase_fault','value':True})
t=None
for i in range(3*3600):
    s.step(1)
    if 'TEMPERATURA ALTA' in s.snapshot()['alarms']:
        t=i; break
assert t is not None and t > 600, t
s=ColdRoom()
s.room=-3.0
for _ in range(400): s.step(1)
s.room=-3.0
for _ in range(700):
    s.step(1); s.room=min(s.room,-1.5)
assert 'TEMPERATURA BAIXA' in s.snapshot()['alarms']
print('OK: dinamica, eventos, alarme, bloqueio, reset, degelo, comandos, aspiracao, degelo sem fase e alarmes de temperatura')
