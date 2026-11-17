"""Simulador didatico de UMA vitrine expositora refrigerada (plug-in, R290, 3 portas de vidro).
Nao controla hardware real. Compativel com MicroPython e CPython, sem dependencias externas.
Os calculos sao aproximacoes para cenarios de teste e formacao, nao engenharia real.

Diferencas face a camara frigorifica (ColdRoom / Pico W):
  - unidade condensadora incorporada (condensador dentro do movel, ar da loja)
  - compressor de velocidade fixa com termostato (liga/desliga) e tempo minimo parado
  - horario da loja: iluminacao LED e clientes a abrir as portas
  - degelo por paragem do compressor (sem resistencia), ventiladores continuam
  - resistencia anti-embaciamento nos vidros, controlada pela humidade da loja
  - sonda de produto (HACCP): minimo, maximo e minutos acima de 5 C
"""
import math

try:
    from random import random as _rnd
except ImportError:  # MicroPython sem funcoes extra de random
    from random import getrandbits

    def _rnd():
        return getrandbits(24) / 16777216


def clamp(x, low, high):
    return max(low, min(high, x))


def psat_r290(t):
    """Pressao de saturacao APROXIMADA do R290 (propano), em bar relativos."""
    return max(0.0, math.exp(9.852 - 2266.0 / (t + 273.15)) - 1.013)


DOORS = 3
FAULTS = ('door_ajar', 'dirty_condenser', 'evap_fan_fault', 'gas_leak',
          'heater_fault', 'lights_fault', 'power_cut')
FAULT_TEXT = {
    'door_ajar': 'porta mal fechada',
    'dirty_condenser': 'condensador sujo',
    'evap_fan_fault': 'ventilador do evaporador avariado',
    'gas_leak': 'fuga de R290',
    'heater_fault': 'resistencia anti-embaciamento avariada',
    'lights_fault': 'iluminacao LED avariada',
    'power_cut': 'falha de energia',
}
TRAFFIC = (0, 12, 30, 60)         # aberturas por hora e por porta: nenhum, baixo, medio, alto
TRAFFIC_TEXT = ('sem clientes', 'baixo', 'medio', 'alto')
START_TOD = 7 * 3600 + 20 * 60    # a simulacao comeca as 07:20
STORE_OPEN, STORE_CLOSE = 8 * 3600, 21 * 3600
LIGHTS_ON, LIGHTS_OFF = 7 * 3600 + 30 * 60, 21 * 3600 + 30 * 60
DEFROST_EVERY = 6 * 3600
DEFROST_MIN = 12 * 60
DEFROST_MAX = 30 * 60
DEFROST_END_C = 3.0               # fim do degelo pela temperatura do evaporador
HP_TRIP_BAR = 20.0                # pressostato de alta
HYST = 0.8                        # histerese do termostato (+/- K)
MIN_OFF_S = 180                   # protecao anti ciclos curtos do compressor
HACCP_LIMIT = 5.0
AJAR_DOOR = 1                     # porta que fica mal fechada (0 = P1, 1 = P2, 2 = P3)
AJAR_INFIL = 0.0003               # folga da porta: cerca de 3/4 de uma porta aberta, continuamente
DOOR_ALARM_S = 120                # porta aberta / mal fechada ha mais de 2 min


class Showcase:
    def __init__(self):
        self.target = 3.0
        self.ambient = 21.0
        self.humidity = 55.0
        self.air = 4.2
        self.product = 3.6
        self.supply = 1.5
        self.return_air = 4.6
        self.evap = -2.0
        self.cond = 24.0
        self.suction = psat_r290(-2.0)
        self.discharge = psat_r290(24.0)
        self.superheat = 6.0
        self.subcooling = 5.0
        self.compressor = False
        self.comp_off_s = MIN_OFF_S
        self.fans = True
        self.cond_fan = False
        self.defrost = False
        self.defrost_elapsed = 0
        self.since_defrost = 2 * 3600
        self.door_timer = [0.0] * DOORS
        self.door_manual = [False] * DOORS
        self.door_cont = [0.0] * DOORS
        self.ajar_s = 0.0
        self.doors = [False] * DOORS
        self.door_openings = 0
        self.schedule = 'auto'
        self.traffic = 2
        self.store_open = False
        self.lights = False
        self.antifog_pct = 0
        self.fog = 0.0
        self.fouling = 0.0
        self.ice = 0.0
        self.faults = dict((f, False) for f in FAULTS)
        self.trip = False
        self.sim_seconds = 0
        self.speed = 5
        self.runtime_compressor = 1843.0   # horas ficticias iniciais
        self.runtime_fans = 2650.0
        self.energy_kwh = 912.0
        self.compressor_starts = 15230
        self.duty = 0.45
        self.power_kw = 0.0
        self.voltage = 230.0
        self.current = 0.0
        self.haccp_min = self.product
        self.haccp_max = self.product
        self.haccp_above_min = 0.0
        self.high_s = 0
        self.low_s = 0
        self.product_high_s = 0
        self.history = []
        self.events = []
        self.last_sample = -60
        self.add_event('INFO', 'Simulador de vitrine inicializado; dados inteiramente ficticios')

    # --- utilitarios ------------------------------------------------------------
    def add_event(self, level, message):
        self.events.insert(0, {'t': int(self.sim_seconds), 'level': level, 'message': message})
        if len(self.events) > 14:
            self.events.pop()

    def tod(self):
        return int(START_TOD + self.sim_seconds) % 86400

    def clock(self):
        t = self.tod()
        return '%02d:%02d' % (t // 3600, (t % 3600) // 60)

    def _store_hours(self, start, end):
        if self.schedule == 'open':
            return True
        if self.schedule == 'closed':
            return False
        return start <= self.tod() < end

    @staticmethod
    def _number(data, low, high, label):
        try:
            value = float(data.get('value'))
        except (ValueError, TypeError):
            raise ValueError('%s invalido' % label)
        if not low <= value <= high:
            raise ValueError('%s permitido: %g a %g' % (label, low, high))
        return value

    # --- comandos ---------------------------------------------------------------
    def action(self, data):
        name = data.get('action', '')
        if name == 'setpoint':
            self.target = self._number(data, -2, 10, 'Setpoint')
            self.add_event('INFO', 'Setpoint alterado para %.1f C' % self.target)
        elif name == 'ambient':
            self.ambient = self._number(data, 15, 35, 'Temperatura da loja')
        elif name == 'humidity':
            self.humidity = self._number(data, 30, 90, 'Humidade')
        elif name == 'speed':
            value = int(data.get('value', 1))
            if value not in (1, 5, 20, 60):
                raise ValueError('Velocidade invalida')
            self.speed = value
        elif name == 'traffic':
            value = int(data.get('value', 0))
            if not 0 <= value < len(TRAFFIC):
                raise ValueError('Trafego invalido (0 a 3)')
            self.traffic = value
            self.add_event('INFO', 'Clientes: %s' % TRAFFIC_TEXT[value])
        elif name == 'schedule':
            value = data.get('value')
            if value not in ('auto', 'open', 'closed'):
                raise ValueError('Horario invalido (auto, open, closed)')
            self.schedule = value
            self.add_event('INFO', 'Horario da loja: %s' % {'auto': 'automatico', 'open': 'sempre aberta',
                                                            'closed': 'fechada'}[value])
        elif name == 'door':
            try:
                i = int(data.get('index', 0))
            except (ValueError, TypeError):
                raise ValueError('Porta invalida')
            if not 0 <= i < DOORS:
                raise ValueError('Porta invalida (0 a %d)' % (DOORS - 1))
            self.door_manual[i] = bool(data.get('value'))
            if self.door_manual[i]:
                self.door_openings += 1
            self.add_event('WARN' if self.door_manual[i] else 'INFO',
                           'Porta %d %s' % (i + 1, 'aberta (manual)' if self.door_manual[i] else 'fechada'))
        elif name == 'fault':
            fault = data.get('name')
            if fault not in FAULTS:
                raise ValueError('Avaria desconhecida')
            self.faults[fault] = bool(data.get('value'))
            on = self.faults[fault]
            self.add_event('ALARM' if on else 'INFO',
                           'Avaria %s: %s' % ('ativada' if on else 'removida', FAULT_TEXT[fault]))
        elif name == 'defrost':
            if not self.defrost:
                self.start_defrost('manual')
        elif name == 'reset':
            if self.faults['dirty_condenser']:
                raise ValueError('Limpa primeiro o condensador (remove a avaria)')
            if self.discharge > HP_TRIP_BAR - 2:
                raise ValueError('Pressao de descarga ainda alta; aguarda que baixe')
            self.trip = False
            self.add_event('INFO', 'Pressostato de alta rearmado')
        elif name == 'restart':
            speed = self.speed
            self.__init__()
            self.speed = speed
        else:
            raise ValueError('Acao nao suportada')

    def start_defrost(self, why):
        self.defrost = True
        self.defrost_elapsed = 0
        self.since_defrost = 0
        self.add_event('INFO', 'Degelo por paragem iniciado (%s)' % why)

    # --- dinamica ---------------------------------------------------------------
    def step(self, dt=1.0):
        # dt em segundos simulados; limitado para estabilidade numerica
        dt = clamp(float(dt), 0.0, 5.0)
        if dt <= 0:
            return
        f = self.faults
        self.sim_seconds += dt
        power = not f['power_cut']

        # Loja: horario, iluminacao e clientes
        was_open, was_lit = self.store_open, self.lights
        self.store_open = self._store_hours(STORE_OPEN, STORE_CLOSE)
        self.lights = power and not f['lights_fault'] and self._store_hours(LIGHTS_ON, LIGHTS_OFF)
        if self.store_open != was_open and self.sim_seconds > dt:
            self.add_event('INFO', 'Loja %s (%s)' % ('aberta' if self.store_open else 'fechada', self.clock()))
        if self.lights != was_lit and power and not f['lights_fault'] and self.sim_seconds > dt:
            self.add_event('INFO', 'Iluminacao %s' % ('ligada' if self.lights else 'desligada'))
        rate = TRAFFIC[self.traffic] if self.store_open else 0
        for i in range(DOORS):
            if self.door_timer[i] > 0:
                self.door_timer[i] = max(0.0, self.door_timer[i] - dt)
            elif rate and not self.door_manual[i] and _rnd() < rate / 3600.0 * dt:
                self.door_timer[i] = 4 + 10 * _rnd()   # cliente abre 4 a 14 s
                self.door_openings += 1
            self.doors[i] = self.door_manual[i] or self.door_timer[i] > 0
            self.door_cont[i] = self.door_cont[i] + dt if self.doors[i] else 0.0
        open_doors = sum(1 for d in self.doors if d)
        # Porta mal fechada: o sensor magnetico deteta a folga (P2 nao fica "fechada")
        self.ajar_s = self.ajar_s + dt if f['door_ajar'] else 0.0
        if f['door_ajar'] and not self.doors[AJAR_DOOR] and self.ajar_s <= dt:
            self.add_event('WARN', 'Sensor da porta %d: porta nao fechou totalmente' % (AJAR_DOOR + 1))

        # Degelo por paragem do compressor (programado)
        self.since_defrost += dt
        if power and not self.defrost and self.since_defrost >= DEFROST_EVERY:
            self.start_defrost('programado')
        if self.defrost:
            self.defrost_elapsed += dt
            if self.defrost_elapsed >= DEFROST_MAX or (self.defrost_elapsed >= DEFROST_MIN and self.evap >= DEFROST_END_C):
                self.defrost = False
                self.add_event('INFO', 'Degelo terminado ao fim de %d min' % (self.defrost_elapsed // 60))

        # Pressostato de alta (rearme manual)
        if self.compressor and self.discharge > HP_TRIP_BAR and not self.trip:
            self.trip = True
            self.add_event('ALARM', 'Pressostato de alta disparou (%.1f bar): compressor parado' % self.discharge)

        # Termostato do compressor (liga/desliga) com tempo minimo parado
        if not power or self.trip or self.defrost:
            if self.compressor and not power:
                self.add_event('ALARM', 'Sem energia: vitrine parada')
            self.compressor = False
        elif not self.compressor and self.air > self.target + HYST and self.comp_off_s >= MIN_OFF_S:
            self.compressor = True
            self.compressor_starts += 1
        elif self.compressor and self.air < self.target - HYST:
            self.compressor = False
        self.comp_off_s = 0 if self.compressor else self.comp_off_s + dt

        self.fans = power and not f['evap_fan_fault']     # continuam durante o degelo por paragem
        self.cond_fan = self.compressor
        self.antifog_pct = round(clamp((self.humidity - 35) * 2.5, 15, 100)) if power and not f['heater_fault'] else 0

        # Condensador sujo: sujidade cresce ate +32 K; limpeza (remover avaria) e rapida
        if f['dirty_condenser']:
            self.fouling += (32 - self.fouling) * min(1, dt / 600)
        else:
            self.fouling += (0 - self.fouling) * min(1, dt / 120)
        # Gelo no evaporador quando o ventilador falha; derrete no degelo
        if self.compressor and not self.fans:
            self.ice = min(1.0, self.ice + dt / 1800)
        elif self.defrost or not self.compressor:
            self.ice = max(0.0, self.ice - dt / (900 if self.defrost else 3600))

        # Condensacao (unidade incorporada, ar da loja)
        cond_t = (self.ambient + 11 + self.fouling) if self.compressor else self.ambient + 1.5
        self.cond += (cond_t - self.cond) * min(1, dt / 30)

        # Balanco termico aproximado (NAO e um modelo de engenharia)
        cap = 0.0065 if self.compressor else 0.0
        if f['gas_leak']:
            cap *= 0.35
        if not self.fans:
            cap *= 0.25
        cap *= (1 - 0.6 * self.ice) * clamp(1 - max(0.0, self.cond - 45) / 40, 0.4, 1)
        infil = 0.0004 * open_doors + (AJAR_INFIL if f['door_ajar'] and not self.doors[AJAR_DOOR] else 0)
        gain = (self.ambient - self.air) * (0.00011 + infil)
        gain += (0.00025 if self.lights else 0) + 0.0001 * self.antifog_pct / 100 + (0.00008 if self.fans else 0)
        self.air += (gain - cap + 0.0006 * (self.product - self.air)) * dt
        self.air = clamp(self.air, -15, 40)
        self.product += (self.air - self.product) * dt / 2400
        if self.compressor:
            evap_t = self.air - (9 if self.fans else 17) - (7 if f['gas_leak'] else 0) - 6 * self.ice
        else:
            evap_t = self.air + (1.5 if self.defrost else -0.5)
        # no degelo o gelo a derreter segura o evaporador perto de 0 C (subida lenta)
        self.evap += (evap_t - self.evap) * min(1, dt / (900 if self.defrost else 20))
        supply_t = self.evap + (0.55 if self.fans else 0.95) * (self.air - self.evap)
        self.supply += (supply_t - self.supply) * min(1, dt / 10)
        self.return_air += ((self.air + 0.5 + (1.5 if open_doors or f['door_ajar'] else 0)) - self.return_air) * min(1, dt / 8)

        # Pressoes (curva aproximada do R290)
        suct_t = psat_r290(self.evap - 3) * (0.8 if f['gas_leak'] else 1) if self.compressor else psat_r290(self.evap)
        self.suction += (max(0.0, suct_t) - self.suction) * min(1, dt / 15)
        self.discharge += (psat_r290(self.cond) * (0.92 if f['gas_leak'] else 1) - self.discharge) * min(1, dt / 15)
        self.superheat = 6 + (10 if f['gas_leak'] else 0) - (4 if not self.fans else 0) if self.compressor else 0.0
        self.subcooling = max(0.5, 5 - (3.5 if f['gas_leak'] else 0) + 0.05 * self.fouling) if self.compressor else 0.0

        # Vidros: sem resistencia e com humidade alta, embaciam
        if self.antifog_pct < 20 and self.humidity > 50:
            self.fog = min(100.0, self.fog + (self.humidity - 50) * dt / 300)
        else:
            self.fog = max(0.0, self.fog - dt / 30)

        # Eletricidade (monofasico 230 V)
        self.voltage = 230 + 3 * math.sin(self.sim_seconds / 71) if power else 0.0
        p_comp = (0.34 + 0.004 * (self.cond - 35)) * (0.85 if f['gas_leak'] else 1) if self.compressor else 0
        self.power_kw = (max(0.0, p_comp) + (0.024 if self.fans else 0) + (0.035 if self.cond_fan else 0)
                         + (0.054 if self.lights else 0) + 0.09 * self.antifog_pct / 100 + 0.006) if power else 0.0
        self.current = self.power_kw * 1000 / (self.voltage * 0.92) if self.voltage else 0.0
        self.energy_kwh += self.power_kw * dt / 3600
        if self.compressor:
            self.runtime_compressor += dt / 3600
        if self.fans:
            self.runtime_fans += dt / 3600
        self.duty += ((1.0 if self.compressor else 0.0) - self.duty) * min(1, dt / 3600)

        # HACCP (sonda de produto) e temporizacoes de alarme
        self.haccp_min = min(self.haccp_min, self.product)
        self.haccp_max = max(self.haccp_max, self.product)
        if self.product > HACCP_LIMIT:
            self.haccp_above_min += dt / 60
        self.product_high_s = self.product_high_s + dt if self.product > HACCP_LIMIT else 0
        self.high_s = self.high_s + dt if (self.air > self.target + 4 and not self.defrost) else 0
        self.low_s = self.low_s + dt if self.air < self.target - 3 else 0

        if self.sim_seconds - self.last_sample >= 60:
            self.history.append([round(self.sim_seconds / 60, 1), round(self.air, 2),
                                 round(self.product, 2), round(self.supply, 2)])
            if len(self.history) > 120:
                self.history.pop(0)
            self.last_sample = self.sim_seconds

    # --- estado -----------------------------------------------------------------
    def alarms(self):
        f = self.faults
        out = []
        if f['power_cut']:
            out.append('FALHA DE ENERGIA')
        if self.high_s > 600:
            out.append('TEMPERATURA ALTA')
        if self.low_s > 600:
            out.append('TEMPERATURA BAIXA')
        if self.product_high_s > 1800:
            out.append('HACCP: PRODUTO > 5 C')
        if max(self.door_cont) > DOOR_ALARM_S:
            out.append('PORTA ABERTA')
        if self.ajar_s > DOOR_ALARM_S:
            out.append('PORTA MAL FECHADA (P%d)' % (AJAR_DOOR + 1))
        if self.trip:
            out.append('ALTA PRESSAO (PRESSOSTATO)')
        if self.cond > 50:
            out.append('CONDENSACAO ALTA')
        if f['evap_fan_fault']:
            out.append('VENTILADOR DO EVAPORADOR')
        if f['gas_leak']:
            out.append('CARGA DE R290 BAIXA')
        if f['heater_fault']:
            out.append('RESISTENCIA ANTI-EMBACIAMENTO')
        if self.fog > 60:
            out.append('VIDROS EMBACIADOS')
        if f['lights_fault'] and self._store_hours(LIGHTS_ON, LIGHTS_OFF):
            out.append('FALHA DE ILUMINACAO')
        return out

    def snapshot(self):
        f = self.faults
        data = {
            'simulated': True, 'type': 'vitrine', 'device': 'ESP32-S3 / Vitrine SIM',
            'model': 'Vitrine 3 portas de vidro, plug-in R290',
            'sim_seconds': round(self.sim_seconds), 'clock': self.clock(), 'speed': self.speed,
            'target': self.target, 'ambient': self.ambient, 'humidity': self.humidity,
            'room': round(self.air, 2), 'product': round(self.product, 2),
            'discharge_air': round(self.supply, 2), 'return_air': round(self.return_air, 2),
            'evaporator': round(self.evap, 2), 'condenser': round(self.cond, 1),
            'suction_bar': round(self.suction, 2), 'discharge_bar': round(self.discharge, 2),
            'superheat': round(self.superheat, 1), 'subcooling': round(self.subcooling, 1),
            'compressor': self.compressor, 'compressor_pct': 100 if self.compressor else 0,
            'duty_pct': round(self.duty * 100), 'compressor_starts': self.compressor_starts,
            'fans': self.fans, 'condenser_fan': self.cond_fan, 'defrost': self.defrost,
            'defrost_in_min': max(0, int((DEFROST_EVERY - self.since_defrost) // 60)),
            'door': any(self.doors) or f['door_ajar'],
            'doors': [d or (f['door_ajar'] and i == AJAR_DOOR) for i, d in enumerate(self.doors)],
            'doors_ajar': [f['door_ajar'] and i == AJAR_DOOR for i in range(DOORS)],
            'doors_manual': list(self.door_manual),
            'door_openings': self.door_openings,
            'store_open': self.store_open, 'schedule': self.schedule, 'traffic': self.traffic,
            'lights': self.lights, 'antifog_pct': self.antifog_pct, 'fog_pct': round(self.fog),
            'voltage': round(self.voltage, 1), 'current': round(self.current, 2),
            'power_kw': round(self.power_kw, 3), 'energy_kwh': round(self.energy_kwh, 2),
            'compressor_hours': round(self.runtime_compressor, 1), 'fan_hours': round(self.runtime_fans, 1),
            'haccp': {'min': round(self.haccp_min, 1), 'max': round(self.haccp_max, 1),
                      'minutes_above': round(self.haccp_above_min), 'limit': HACCP_LIMIT},
            'phase_ok': not f['power_cut'], 'refrigerant_ok': not f['gas_leak'],
            'trip': self.trip, 'faults': dict(f), 'alarms': self.alarms(),
            'history': self.history, 'events': self.events,
        }
        return data
