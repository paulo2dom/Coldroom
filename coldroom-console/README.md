# ColdRoom · Consola central

Consola web que recolhe, via Mosquitto, o estado de várias câmaras frigoríficas
(Pico W) e mostra tudo em tempo real. Corre num Raspberry Raspberry Pi 3 B.

```
Pico W (CF-01) ─┐
Pico W (CF-02) ─┼─► Mosquitto ─► coldroom_console.py ─► browser (SSE, tempo real)
Pico W (…)     ─┘                (Raspberry Pi 3 B :8090)
```

## Ficheiros

| Ficheiro | Função |
|---|---|
| `coldroom_console.py` | Serviço: subscreve o MQTT, guarda estado/histórico em memória, serve a consola |
| `coldroom_examples.py` | Serviço: publica as câmaras de exemplo no Mosquitto (uma ligação MQTT por câmara) |
| `demo_sim.py` | Modelo das câmaras simuladas (exemplos e `--demo`), payload no formato do Pico W |
| `config.py` | Broker, porta web, autenticação, limites de alarme, câmaras de exemplo |
| `static/index.html` | Interface (sem CDN — funciona sem Internet) |
| `coldroom-console.service`, `coldroom-examples.service` | Unidades systemd |
| `coldroom_ble.py` + `coldroom-ble.service` | Configuração das redes Wi-Fi do Pi por Bluetooth LE (`ColdRoom-Pi`, corre como root) |
| `install.sh` | Instala/atualiza tudo no Pi (mantém o `config.py` existente) |

## Instalação no Raspberry Pi 3 B

```bash
sudo apt update && sudo apt install -y python3-paho-mqtt
sudo mkdir -p /opt/coldroom-console
sudo cp -r coldroom_console.py config.py static /opt/coldroom-console/
sudo chown -R pi:pi /opt/coldroom-console          # ajusta o utilizador
nano /opt/coldroom-console/config.py                # MQTT_HOST, etc.

sudo cp coldroom-console.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now coldroom-console
journalctl -u coldroom-console -f
```

Abre `http://<ip-do-pi>:8090/`.

Testar sem broker (simula 12 câmaras, uma com fuga de refrigerante e outra que
deixa de comunicar ao fim de 40 s):

```bash
python3 coldroom_console.py --demo 12
```

## Redes Wi-Fi por Bluetooth

O serviço **`coldroom-ble`** anuncia `ColdRoom-Pi` por Bluetooth LE durante 10 min após o
arranque e sempre que o Pi não tem Wi-Fi. Permite ver o estado/IP e adicionar ou remover
redes (via `wpa_cli`, sem cortar a ligação atual) a partir do PC:

```powershell
py desktop\coldroom_ble.py pi status
py desktop\coldroom_ble.py pi add --ssid "RedeLoja"
```

Ver a secção *Redes Wi-Fi e Bluetooth* do README do Pico (`Coldroom/README.md`). Para abrir
uma janela nova sem reiniciar o Pi: `sudo systemctl restart coldroom-ble`.

- O intervalo de anúncio BLE é reduzido para 100–150 ms (o BlueZ usa 1,28 s, e o Windows
  perdia muitos anúncios).
- Cópia do ficheiro de redes antes desta funcionalidade: `/root/wpa_supplicant.conf.antes-ble`.

## Câmaras de exemplo

Além dos dados reais (só a **CF-01**, o Pico W, publica no Mosquitto), a consola
cria 5 câmaras de exemplo definidas em `EXAMPLE_DEVICES` no `config.py`:

| Câmara | Localização | Setpoint |
|---|---|---|
| CF-02 | PT / Norte / Porto Boavista / Peixaria | 0 °C |
| CF-03 | PT / Norte / Porto Boavista / Congelados | −20 °C |
| CF-04 | PT / Norte / Braga Centro / Talho | 2 °C |
| CF-05 | PT / Centro / Coimbra Baixa / Lacticínios | 4 °C |
| CF-06 | PT / Sul / Lisboa Colombo / Frutas e Legumes | 6 °C |

São publicadas no Mosquitto pelo serviço **`coldroom-examples`**, como se fossem
Picos W: cada câmara tem a sua ligação MQTT, publica `online` em `…/status` ao
ligar (com *last will* `offline`) e o estado em `…/state` a cada 5 s, retido, no
mesmo formato JSON do Pico. Aparecem com **(exemplo)** no nome. A consola
recebe-as pelo broker, tal como a CF-01; qualquer outro cliente MQTT também as vê.

```
Pico W (CF-01) ──────────────┐
coldroom-examples (CF-02…06) ┼─► Mosquitto ─► coldroom-console ─► browser
```

```bash
sudo systemctl status coldroom-examples     # estado do serviço
sudo systemctl stop coldroom-examples       # parar: as 5 câmaras ficam OFFLINE na consola
```

Para remover as câmaras: `EXAMPLE_DEVICES = []` no `config.py` e
`sudo systemctl restart coldroom-examples`. As últimas mensagens ficam retidas
no broker; para as apagar de vez:
`mosquitto_pub -h 127.0.0.1 -r -n -t 'pt/norte/porto-boavista/peixaria/cf-02/state'`
(e o mesmo para `…/status` e para cada câmara).

Modelo (em tempo real, 1 atualização a cada 5 s — `demo_sim.py`):

- **Temperatura:** ganha 0,1–0,2 °C/min; o compressor arrefece até ~0,6 °C/min,
  conforme a carga. Liga acima de setpoint + 1,0 °C e desliga abaixo de
  setpoint − 0,8 °C → ciclos de ~20 min, compressor ~45 % do tempo.
- **Degelo:** 10 min, a cada 2–4 h (o primeiro 5–60 min após o arranque).
- **Porta:** ~1 abertura a cada 20 min; 30 % ficam abertas mais de 60 s e geram
  o alarme **"PORTA ABERTA HA MAIS DE 60 s"** (`DOOR_ALARM_S`) só a partir desse momento.
- **Pressões:** a aspiração segue a pressão de saturação aproximada de um R404A
  à temperatura do evaporador, por isso depende do setpoint (congelados −20 °C ≈ 1,2 bar;
  +6 °C ≈ 4,7 bar com o compressor ligado). Descarga ≈ 16 bar ligado, 10,5 bar parado.
- **Contadores** (energia, horas): valor base fixo por câmara (derivado do tópico)
  mais uma média desde 2025-01-01, por isso não mudam quando o serviço reinicia.
- **Modo:** REFRIGERAÇÃO / STANDBY / DEGELO, como a CF-01.

## Tópicos

`pais/zona/loja/local/equipamento/state` — ex.: `pt/norte/porto-boavista/talho/cf-01/state`

A localização vem do tópico e é formatada para leitura:
`porto-boavista` → **Porto Boavista**, `vila-nova-de-gaia` → **Vila Nova de Gaia**,
`pt` → **PT**, `cf-01` → **CF-01**.

Opcional: `…/cf-01/status` com `online`/`offline` (LWT do Pico). Se o equipamento
publicar `offline`, a consola marca-o logo como **OFFLINE** em vez de esperar
pelo `STALE_AFTER_S`.

## Payload JSON esperado

O parser aceita várias grafias de chaves (ver `normalize()` no código). Este é o
formato de referência:

```json
{
  "name": "Câmara frigorífica CF-01",
  "mode": "STANDBY", "uptime_s": 1320, "speed": 5,
  "temp": {"room": 2.4, "setpoint": 2.0, "supply": 2.3, "return": 2.7, "evap": 1.4},
  "compressor": {"on": false, "load": 0, "protection": "Normal", "hours": 3217.2},
  "fans": {"on": true, "hours": 4802.0},
  "eev": {"opening": 0},
  "defrost": {"active": false},
  "door": {"open": false},
  "pressure": {"suction": 2.50, "discharge": 7.80},
  "superheat": 5.50, "subcooling": 5.00,
  "electrical": {"voltage": 401.8, "current": 0.30, "power_kw": 0.18, "energy_kwh": 1254.44},
  "status": {"phase_monitor": "Normal", "compressor_oil": "Normal", "refrigerant": "Normal"},
  "alarms": [{"code": "HT", "text": "Temperatura alta", "severity": "critical"}]
}
```

Se o teu Pico usar outras chaves, abre a câmara na consola → **Payload JSON
recebido** e acrescenta a chave à lista correspondente em `normalize()`.

## Estado do MQTT (topo da consola)

| Indicador | Quando |
|---|---|
| **● MQTT LIGADO** (verde) | ligado ao broker |
| **● MQTT SEM LIGAÇÃO** (laranja) | broker em baixo; o paho deteta em ~1,5 × `MQTT_KEEPALIVE` (≈ 20 s com 15 s) |
| **MQTT DESATIVADO** | `MQTT_HOST` apagado/comentado no `config.py` |
| **● MODO DEMO** | arrancado com `--demo` |

Se o browser perder a ligação à própria consola aparece uma faixa vermelha e
volta a ligar sozinho.

## Alarmes

- Os enviados pelo equipamento (`alarms`).
- **COMM** — sem mensagens há mais de `STALE_AFTER_S` (60 s) ou LWT `offline`.
- **TEMP_HIGH** — câmara acima de `setpoint + TEMP_HIGH_DELTA` durante
  `TEMP_HIGH_DELAY_S` (ignorado em degelo; desliga com `TEMP_HIGH_DELTA = None`).

Cada início/fim de alarme fica no **Registo de eventos** (em memória, últimos 300).

## Notas

- Histórico: 1 ponto/10 s, 2 h por câmara, em RAM (≈ 50 KB por câmara). Perde-se ao reiniciar.
- **Segurança (decisão de 2026-11-15):** a consola fica **sem password**, de propósito, por ser um
  simulador com dados fictícios numa rede local. Qualquer pessoa na rede pode abrir
  `http://192.168.68.123:8090/`. O Mosquitto também aceita ligações sem autenticação e sem TLS.
  Não usar esta configuração com equipamentos ou dados reais.
- **Bluetooth:** a configuração por BLE não é cifrada (a password Wi-Fi passa em claro); fica
  ativa só em janelas curtas (10 min após arrancar ou sem Wi-Fi).
- Para expor fora da LAN: ativa `HTTP_USER`/`HTTP_PASSWORD` e põe à frente um
  reverse proxy com TLS (nginx/Caddy). No MQTT, usa `MQTT_TLS = True` na porta 8883.
- Separador do browser: `ColdRoom | Consola central` na vista geral e
  `ColdRoom | CF-01 · Porto Boavista` no detalhe de cada câmara.
