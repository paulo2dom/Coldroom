# Vitrine SIM: vitrine expositora refrigerada virtual no ESP32-S3 Supermini

O **ESP32-S3 Supermini é o simulador** de uma vitrine expositora **VT-01** de supermercado: 3 portas de vidro, unidade plug-in a R290 (propano), produtos lácteos a +3 °C. Não precisa de sensores nem relés. Corre um modelo simplificado, gera dados e alarmes fictícios, serve um site local com controlos de cenário e publica no broker MQTT do Raspberry Pi, onde aparece na mesma consola que a câmara CF-01 (Pico W).

É um simulador **diferente** do ColdRoom (pasta acima). Partilham a rede, o MQTT, a localização e a configuração por Bluetooth; o modelo de refrigeração, a página e o hardware são próprios.

## Diferenças face à câmara frigorífica (ColdRoom / Pico W)

| | Câmara CF-01 (Pico W) | Vitrine VT-01 (ESP32-S3) |
|---|---|---|
| Equipamento | Câmara de refrigerados, unidade remota, trifásico 400 V | Vitrine de 3 portas de vidro, unidade incorporada (plug-in), monofásico 230 V |
| Refrigerante | Índices sintéticos | R290, pressões por curva aproximada |
| Compressor | Capacidade variável (%) | Velocidade fixa: termostato liga/desliga (±0,8 K), mínimo 3 min parado |
| Degelo | Resistência elétrica | Por paragem do compressor, a cada 6 h, entre 12 e 30 min |
| Utilização | Porta aberta manualmente | Horário da loja (08:00–21:00) e clientes que abrem as portas sozinhos |
| Extras | Válvula EEV, óleo, fases | Iluminação LED, resistência anti-embaciamento, sonda de produto (HACCP) |

## Ficheiros

- `main.py`: Wi-Fi, servidor HTTP, API JSON, MQTT e Bluetooth
- `simulator.py`: modelo da vitrine (classe `Showcase`)
- `index.html`: dashboard standalone (HTML, CSS e JavaScript, sem CDN)
- `board.py`: hardware do Supermini (LED RGB WS2812 no GPIO48, botão BOOT no GPIO0)
- `mqtt_pub.py`, `location.py`, `netcfg.py`, `ble_setup.py`: iguais aos do ColdRoom
- `config.py`: configuração real (Wi-Fi, MQTT, localização). **Não partilhar.**
- `config.example.py`: modelo de configuração
- `desktop/preview.py`: o mesmo simulador e dashboard no PC (http://127.0.0.1:8767)
- `desktop/vitrine_ble.py`: configurar redes Wi-Fi por Bluetooth a partir do PC
- `tests/test_simulator.py`: verificações automáticas do modelo
- `.vscode/tasks.json`: tarefas do VS Code (enviar, consola série, pré-visualizar, testes)

## Testar sem ESP32

```powershell
py desktop/preview.py
py tests/test_simulator.py
```

## Instalar no ESP32-S3 Supermini

1. **Firmware** (só uma vez): `py -m pip install esptool`. Descarregar `ESP32_GENERIC_S3-…-v1.29.0.bin` de https://micropython.org/download/ESP32_GENERIC_S3/ (serve para 4 MB de flash e deteta a PSRAM).

```powershell
py -m esptool --chip esp32s3 --port COM15 erase-flash
py -m esptool --chip esp32s3 --port COM15 --baud 460800 write-flash 0 ESP32_GENERIC_S3-20260824-v1.29.0.bin
```

   Se o PC não detetar a placa: manter BOOT premido, carregar em RESET e largar BOOT. **Depois do MicroPython a porta muda** (aqui passou de COM15 para COM16; confirmar com `py -m mpremote connect list`).

2. **Ficheiros** (ou a tarefa do VS Code *Vitrine: enviar para o ESP32*):

```powershell
py -m mpremote connect COM16 cp simulator.py mqtt_pub.py location.py netcfg.py ble_setup.py board.py index.html config.py main.py : + reset
```

3. Abrir `http://IP_DO_ESP32/`. O IP aparece na consola série (`py -m mpremote connect COM16 repl`) ou no router.

O MicroPico (extensão do VS Code) é só para o Pico. Se estiver ligado, ocupa a porta: desliga-o antes de usar o `mpremote`. Nesta pasta está configurado para não ligar sozinho.

## O que simula

- **Termostato** sobre o ar da vitrine (setpoint −2 a 10 °C, por omissão 3 °C).
- **Produto**: sonda que segue o ar lentamente (constante de tempo de cerca de 40 min). HACCP com mínimo, máximo e minutos acima de 5 °C.
- **Loja**: o relógio simulado começa às 07:20. Iluminação das 07:30 às 21:30, loja aberta das 08:00 às 21:00. Pode forçar-se "Aberta" ou "Fechada".
- **Clientes**: com a loja aberta, cada porta abre sozinha (4 a 14 s) com a frequência escolhida: nenhum, baixo (12/h), médio (30/h) ou alto (60/h). Também se pode abrir cada porta à mão.
- **Degelo por paragem**: compressor parado e ventiladores ligados. Termina com o evaporador a 3 °C, no mínimo ao fim de 12 min e no máximo de 30 min.
- **Anti-embaciamento**: a resistência dos vidros sobe com a humidade da loja. Sem ela, e com humidade acima de 50 %, os vidros embaciam.
- **Energia**: compressor (cerca de 0,35 kW, sobe com a condensação), ventiladores, LED, resistência e controlador. Em média de 7 a 8 kWh por dia com tráfego médio.

### Avarias para injetar

| Avaria | O que acontece | Alarme |
|---|---|---|
| Porta mal fechada | A porta 2 fica com folga: o sensor magnético deteta-a, entra ar quente e o compressor trabalha muito mais | **PORTA MAL FECHADA (P2)** em 2 min; depois HACCP e TEMPERATURA ALTA |
| Condensador sujo | A condensação sobe aos poucos até o pressostato de alta disparar (cerca de 20 min simulados) | CONDENSACAO ALTA, depois ALTA PRESSAO. Rearme só depois de limpar |
| Ventilador do evaporador | O evaporador gela, a aspiração baixa e o ar aquece | VENTILADOR DO EVAPORADOR, depois TEMPERATURA ALTA |
| Fuga de R290 | Aspiração baixa, superaquecimento alto, compressor sempre ligado | CARGA DE R290 BAIXA, depois HACCP e TEMPERATURA ALTA |
| Anti-embaciamento | Vidros embaciam se a humidade for alta (testar com 75 %) | RESISTENCIA ANTI-EMBACIAMENTO, VIDROS EMBACIADOS |
| Iluminação LED | LED apagado no horário da loja | FALHA DE ILUMINACAO |
| Falha de energia | Tudo desligado (0 V, 0 W); a temperatura sobe | FALHA DE ENERGIA, depois TEMPERATURA ALTA e HACCP |

Outros alarmes: **PORTA ABERTA** (uma porta aberta há mais de 2 min), **TEMPERATURA ALTA** ou **BAIXA** (mais de 4 K acima ou 3 K abaixo do setpoint durante 10 min), **HACCP: PRODUTO > 5 C** (durante 30 min).

## API

- `GET /api/state`: estado completo, com `location`, `mqtt`, `wifi` e `ble`
- `POST /api/action` (JSON):
  - `{"action":"setpoint","value":3}`, `ambient` (15–35), `humidity` (30–90)
  - `{"action":"speed","value":60}` (1, 5, 20 ou 60)
  - `{"action":"schedule","value":"auto"}` (`auto`, `open` ou `closed`)
  - `{"action":"traffic","value":2}` (0 a 3)
  - `{"action":"door","index":0,"value":true}` (portas 0, 1 e 2)
  - `{"action":"fault","name":"gas_leak","value":true}`: `door_ajar`, `dirty_condenser`, `evap_fan_fault`, `gas_leak`, `heater_fault`, `lights_fault`, `power_cut`
  - `{"action":"defrost"}`, `{"action":"reset"}` (rearmar o pressostato), `{"action":"restart"}`

## MQTT e consola do Raspberry Pi

- Tópico: `pt/norte/porto-boavista/lacticinios/vt-01/state` (retido, de 5 em 5 s) e `…/status` (`online`/`offline`, com last will).
- Identificador MQTT `Vitrine-SIM-01`. Tem de ser diferente do Pico e dos outros equipamentos, senão o broker desliga um deles.
- O JSON usa os mesmos nomes que o Pico para os campos comuns (`room`, `target`, `discharge_air`, `return_air`, `evaporator`, `compressor`, `fans`, `defrost`, `door`, `suction_bar`, `discharge_bar`, `power_kw`, `alarms`, …), por isso a consola do Pi (`coldroom-console`) mostra a vitrine sem alterações. Os campos próprios (`product`, `doors`, `lights`, `store_open`, `haccp`, `fog_pct`, …) também seguem no JSON e `type` vale `"vitrine"`.

## Redes Wi-Fi e Bluetooth

Funciona como no Pico: várias redes em `WIFI_NETWORKS` no `config.py`, mais as adicionadas por Bluetooth (ficam em `networks.json`). O nome Bluetooth é **`Vitrine-VT-01`**.

O Bluetooth está ativo nos primeiros 3 min após arrancar, quando não há Wi-Fi conhecido, ou durante 5 min depois de premir **BOOT 1 s**. Enquanto está ativo, o LED RGB junto ao chip fica azul (fixo).

```powershell
py desktop\vitrine_ble.py scan
py desktop\vitrine_ble.py vitrine status
py desktop\vitrine_ble.py vitrine add --ssid "RedeLab" --mqtt-host 192.168.1.50
py desktop\vitrine_ble.py vitrine apply
```

LEDs da placa: o **RGB junto ao chip** (WS2812 no GPIO48, `LED_RGB = True`, testado) é o indicador do Bluetooth. O **azul a piscar junto ao USB-C ("BAT")** é do carregador de bateria: pisca sempre que não há bateria ligada, é normal e o programa não o controla.

### Exemplo: rede preferida e rede de reserva

Exemplo genérico com duas redes (substituir pelos nomes, passwords e IPs reais no `config.py` de cada equipamento):

| Equipamento | `RedeLab` (preferida, IP fixo) | `RedeReserva` (reserva, DHCP) |
|---|---|---|
| Raspberry Pi (broker e consola) | 192.168.10.15 (`/etc/dhcpcd.conf`, bloco `ssid`) | 192.168.1.50 (reserva DHCP no router) |
| Pico W (CF-01) | 192.168.10.16 | atribuído pelo router |
| ESP32-S3 (VT-01) | 192.168.10.17 | atribuído pelo router |

```python
WIFI_NETWORKS = [
    {'ssid': 'RedeReserva', 'password': '...', 'mqtt_host': '192.168.1.50', 'priority': 1},
    {'ssid': 'RedeLab', 'password': '...', 'mqtt_host': '192.168.10.15',
     'ip': '192.168.10.16/24', 'gw': '192.168.10.1', 'priority': 2},   # Pico .16, ESP32 .17
]
```

- Router da `RedeLab`: 192.168.10.1 (/24). A prioridade tem de ser a mesma nos três equipamentos (`RedeLab` 2, `RedeReserva` 1), para nunca ficarem em redes diferentes.
- No `config.py`, cada rede pode ter `ip` (IP fixo), `gw`, `priority` e `mqtt_host`.
- **Mudança automática de rede:** se o Wi-Fi cair mais de 30 s, o equipamento reinicia e liga-se à melhor rede disponível (sem a preferida, vai para a de reserva). Se estiver na rede de reserva, de 5 em 5 min procura a preferida e, se a vir, reinicia para voltar a ela. O Pi faz o mesmo de 2 em 2 min com o `coldroom-wifi-prefer.timer` (pasta `coldroom-console`).
- **Descoberta do broker:** a consola do Pi anuncia o broker por UDP (porta 47830) de 5 em 5 s. Numa rede sem `mqtt_host`, ou se o broker falhar 2 vezes, o Pico e o ESP32 usam o IP desse anúncio.

## Watchdog e causa do arranque

O `main.py` ativa o watchdog do ESP32 (`WDT_S = 30` por omissão; `WDT_S = 0` no `config.py` desliga-o). Se o ciclo principal parar mais de 30 s, o ESP32 reinicia sozinho e volta ao broker.

Para aquecer menos, o processador corre a 160 MHz (`CPU_MHZ`) e, com bom sinal (RSSI acima de −67 dBm), a potência do Wi-Fi baixa para 13 dBm (`WIFI_TXPOWER`; 0 deixa o máximo). Na API e no MQTT seguem também `mcu_temp_c` (temperatura do chip), `rssi`, `txpower`, `cpu_mhz` e `mem_free`.

A causa do último arranque segue em `reset_cause` na API e no MQTT: `pwron` (ligado à corrente), `hard` (botão RST ou `mpremote reset`), `wdt` (bloqueio apanhado pelo watchdog) ou `soft`. Junto vai `uptime_s`, o tempo real desde o arranque. Se aparecer `wdt`, a placa bloqueou e recuperou sozinha.

## Segurança e limitações

- Simulador didático: valores fictícios. Não usar para controlo real nem para conformidade alimentar.
- O site e a API não têm autenticação; usar só na rede do laboratório.
- O Bluetooth não é cifrado: a password Wi-Fi passa em claro durante a configuração. Por isso só fica ativo em janelas curtas.
- O R290 é inflamável. O simulador não modela nenhum aspeto de segurança do gás.
