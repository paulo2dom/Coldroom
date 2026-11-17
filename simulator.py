"""Simulador didatico de UMA camara frigorifica. Nao controla hardware real.
Compatível com MicroPython e CPython, sem dependencias externas.
Os calculos termodinamicos sao aproximacoes inventadas para cenarios de teste.
"""
import math
import time


def clamp(x, low, high):
    return max(low, min(high, x))


class ColdRoom:
    def __init__(self):
        self.target = 2.0
        self.ambient = 24.0
        self.room = 4.7
        self.discharge_air = 2.7
        self.return_air = 4.9
        self.evap = -3.5
        self.suction = 2.3
        self.discharge_pressure = 12.4
        self.suction_line = 3.1
        self.liquid_line = 30.0
        self.compressor = False
        self.fans = True
        self.valve = 0.0
        self.capacity = 0.0
        self.defrost = False
        self.defrost_elapsed = 0
        self.since_defrost = 0
        self.door = False
        self.phase_fault = False
        self.oil_fault = False
        self.low_refrigerant = False
        self.hp_fault = False
        self.trip = False
        self.alarms_latched = False
        self.sim_seconds = 0
        self.runtime_compressor = 3217.0  # horas ficticias iniciais
        self.runtime_fans = 4802.0
        self.energy_kwh = 1254.0
        self.power_kw = 0.0
        self.voltage = 400.0
        self.current = 0.0
        self.phase_ok = True
        self.speed = 5
        self.history = []
        self.events = []
        self.last_sample = -30
        self.add_event('INFO', 'Simulador inicializado; dados inteiramente ficticios')

    def add_event(self, level, message):
        self.events.insert(0, {'t': int(self.sim_seconds), 'level': level, 'message': message})
        if len(self.events) > 12:
            self.events.pop()

    def action(self, data):
        name = data.get('action', '')
        if name == 'setpoint':
            try:
                value = float(data.get('value'))
            except (ValueError, TypeError):
                raise ValueError('Setpoint invalido')
            if not -18.0 <= value <= 12.0:
                raise ValueError('Setpoint permitido: -18 a 12 C')
            self.target = value
            self.add_event('INFO', 'Setpoint alterado para %.1f C' % value)
        elif name == 'ambient':
            try:
                value = float(data.get('value'))
            except (ValueError, TypeError):
                raise ValueError('Temperatura ambiente invalida')
            if not 15 <= value <= 40:
                raise ValueError('Ambiente permitido: 15 a 40 C')
            self.ambient = value
        elif name == 'speed':
            value = int(data.get('value', 1))
            if value not in (1, 5, 20):
                raise ValueError('Velocidade invalida')
            self.speed = value
        elif name == 'door':
            self.door = bool(data.get('value'))
            self.add_event('WARN' if self.door else 'INFO', 'Porta aberta' if self.door else 'Porta fechada')
        elif name == 'fault':
            fault = data.get('name')
            if fault not in ('phase_fault', 'oil_fault', 'low_refrigerant', 'hp_fault'):
                raise ValueError('Avaria desconhecida')
            setattr(self, fault, bool(data.get('value')))
            self.add_event('ALARM' if getattr(self, fault) else 'INFO', 'Avaria %s %s' % (fault, 'ativada' if getattr(self, fault) else 'removida'))
        elif name == 'defrost':
            if not self.defrost:
                self.start_defrost()
        elif name == 'reset':
            if self.phase_fault or self.oil_fault or self.hp_fault:
                raise ValueError('Remove primeiro as avarias ativas')
            self.trip = False
            self.alarms_latched = False
            self.add_event('INFO', 'Protecao rearmada')
        elif name == 'restart':
            self.__init__()
        else:
            raise ValueError('Acao nao suportada')

    def start_defrost(self):
        self.defrost = True
        self.defrost_elapsed = 0
        self.since_defrost = 0
        self.add_event('INFO', 'Ciclo de degelo iniciado')

    def step(self, dt=1.0):
        # dt em segundos simulados; iteracao limitada para estabilidade numerica
        dt = clamp(float(dt), 0.0, 5.0)
        self.sim_seconds += dt
        self.since_defrost += dt
        if self.since_defrost > 6 * 3600 and not self.defrost:
            self.start_defrost()
        if self.phase_fault or self.oil_fault or self.hp_fault:
            if not self.trip:
                self.add_event('ALARM', 'Protecao de seguranca: compressor bloqueado')
            self.trip = True
            self.alarms_latched = True
        if self.defrost:
            self.defrost_elapsed += dt
            if self.defrost_elapsed > 240 or self.evap > 8.0:
                self.defrost = False
                self.add_event('INFO', 'Ciclo de degelo terminado')
        if not self.trip and not self.defrost:
            if self.room > self.target + 0.6:
                self.compressor = True
            elif self.room < self.target - 0.6:
                self.compressor = False
        else:
            self.compressor = False

        self.fans = not self.defrost and not self.phase_fault
        # Resistencia de degelo precisa de tensao: sem fase o degelo fica sem aquecimento
        heater = self.defrost and not self.phase_fault
        ideal_capacity = clamp(45 + (self.room - self.target) * 12, 35, 100) if self.compressor else 0
        if self.low_refrigerant:
            ideal_capacity *= 0.45
        self.capacity += (ideal_capacity - self.capacity) * min(1, dt / 6)
        self.valve += ((clamp(35 + (self.room - self.target) * 7, 20, 92) if self.compressor else 0) - self.valve) * min(1, dt / 8)

        # Equilibrio termico aproximado, NAO uma simulacao de engenharia fisica
        heat_gain = (self.ambient - self.room) * (0.00042 if self.door else 0.000065)
        cooling = (self.capacity / 100.0) * 0.012 if self.compressor else 0.0
        warming_defrost = 0.018 if heater else 0.0
        self.room += (heat_gain - cooling + warming_defrost) * dt
        self.room = clamp(self.room, -24, 45)
        target_evap = (6.5 if heater else self.room - (6.5 if self.compressor else 1.0))
        self.evap += (target_evap - self.evap) * min(1, dt / 16)
        target_supply = (self.room - (2.0 + self.capacity * 0.045)) if self.compressor else self.room + (0.4 if heater else -0.1)
        self.discharge_air += (target_supply - self.discharge_air) * min(1, dt / 12)
        self.return_air += ((self.room + (0.8 if self.door else 0.3)) - self.return_air) * min(1, dt / 8)

        # Limite inferior para a pressao de aspiracao nao ficar negativa em congelacao
        suction_target = max(0.2, ((1.5 + 0.09 * self.room) if self.compressor else 2.5) - (0.7 if self.low_refrigerant else 0))
        self.suction += (suction_target - self.suction) * min(1, dt / 15)
        high_target = (11.5 + 0.11 * (self.ambient - 20) + self.capacity * 0.03) if self.compressor else 7.8
        if self.hp_fault:
            high_target = 25.0
        self.discharge_pressure += (high_target - self.discharge_pressure) * min(1, dt / 12)
        self.suction_line = self.evap + 5.5 + (4 if self.low_refrigerant else 0)
        self.liquid_line = self.ambient + 6.0 - (2 if self.compressor else 0)
        # Indicadores inventados; nao usar para diagnostico tecnico real
        self.superheat = 5.5 + (4 if self.low_refrigerant else 0) + 0.02 * self.capacity
        self.subcooling = max(0, 5.0 - (3.5 if self.low_refrigerant else 0) + 0.012 * self.capacity)
        self.phase_ok = not self.phase_fault
        self.voltage = 0 if self.phase_fault else 400 + 2.5 * math.sin(self.sim_seconds / 63)
        self.power_kw = ((0.5 + self.capacity / 100.0 * 3.3) if self.compressor else 0) + (0.18 if self.fans else 0) + (2.2 if heater else 0)
        self.current = (self.power_kw * 1000 / (1.732 * max(self.voltage, 1) * 0.86)) if self.voltage > 0 else 0
        self.energy_kwh += self.power_kw * dt / 3600
        if self.compressor:
            self.runtime_compressor += dt / 3600
        if self.fans:
            self.runtime_fans += dt / 3600
        if self.sim_seconds - self.last_sample >= 30:
            self.history.append([round(self.sim_seconds / 60, 1), round(self.room, 2), round(self.discharge_air, 2), round(self.return_air, 2)])
            if len(self.history) > 80:
                self.history.pop(0)
            self.last_sample = self.sim_seconds

    def snapshot(self):
        alarms = []
        if self.door:
            alarms.append('PORTA ABERTA')
        if self.phase_fault:
            alarms.append('FALHA DE FASE')
        if self.oil_fault:
            alarms.append('NIVEL DE OLEO BAIXO')
        if self.hp_fault:
            alarms.append('ALTA PRESSAO')
        if self.low_refrigerant:
            alarms.append('REFRIGERANTE BAIXO')
        if self.trip:
            alarms.append('COMPRESSOR BLOQUEADO')
        return {
            'simulated': True, 'device': 'Pico W / ColdRoom SIM',
            'sim_seconds': round(self.sim_seconds), 'speed': self.speed,
            'target': self.target, 'ambient': self.ambient,
            'room': round(self.room, 2), 'discharge_air': round(self.discharge_air, 2),
            'return_air': round(self.return_air, 2), 'evaporator': round(self.evap, 2),
            'suction_bar': round(self.suction, 2), 'discharge_bar': round(self.discharge_pressure, 2),
            'superheat': round(self.superheat if hasattr(self, 'superheat') else 5.5, 2),
            'subcooling': round(self.subcooling if hasattr(self, 'subcooling') else 5.0, 2),
            'compressor': self.compressor, 'compressor_pct': round(self.capacity),
            'fans': self.fans, 'expansion_pct': round(self.valve),
            'defrost': self.defrost, 'door': self.door, 'phase_ok': self.phase_ok,
            'voltage': round(self.voltage, 1), 'current': round(self.current, 2),
            'power_kw': round(self.power_kw, 2), 'energy_kwh': round(self.energy_kwh, 2),
            'compressor_hours': round(self.runtime_compressor, 1), 'fan_hours': round(self.runtime_fans, 1),
            'oil_ok': not self.oil_fault, 'refrigerant_ok': not self.low_refrigerant,
            'phase_fault': self.phase_fault, 'oil_fault': self.oil_fault,
            'low_refrigerant': self.low_refrigerant, 'hp_fault': self.hp_fault,
            'trip': self.trip, 'alarms': alarms,
            'history': self.history, 'events': self.events
        }
