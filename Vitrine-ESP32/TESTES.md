# Plano de testes: Vitrine SIM (ESP32-S3)

| Item | Valor |
|---|---|
| Dashboard | `http://192.168.68.124/` (confirmar IP no router se mudar) |
| Porta série | COM16 (MicroPython); COM15 só em modo de instalação de firmware |
| Broker | 192.168.68.123, tópico `pt/norte/porto-boavista/lacticinios/vt-01/state` |
| Consola central | `http://192.168.68.123:8090/` |

Usar a velocidade **60×** para os testes longos: 1 min real equivale a 1 h simulada. O relógio no topo mostra a hora da loja e o tempo decorrido (T+).

## 1. Arranque e página

- [ ] **TV.1 — Arranque:** desligar e ligar o USB. Esperar cerca de 15 s.
  **Esperado:** a página abre; aparece "SIMULADOR ONLINE" e "MQTT LIGADO"; o LED RGB junto ao chip fica azul durante 3 min (Bluetooth). O azul a piscar junto ao USB-C ("BAT") é do carregador e é normal.
- [ ] **TV.2 — Hora da loja:** logo após arrancar.
  **Esperado:** relógio às 07:20, "LOJA FECHADA", iluminação "Desligada (noite)". Às 07:30 a iluminação liga; às 08:00 a loja abre e as portas começam a abrir sozinhas (P1–P3 a laranja).

## 2. Funcionamento normal

- [ ] **TV.3 — Termostato:** 60×, loja aberta, clientes "Médio", durante 5 min reais.
  **Esperado:** o ar oscila entre cerca de 2 e 5 °C, o compressor liga e desliga, funcionamento entre 40 e 75 %, sem alarmes.
- [ ] **TV.4 — Clientes:** mudar para "Alto" e depois para "Nenhum".
  **Esperado:** com "Alto" as aberturas sobem depressa e o funcionamento aproxima-se de 80–90 %; com "Nenhum" deixa de haver aberturas.
- [ ] **TV.5 — Loja fechada:** carregar em "Fechada".
  **Esperado:** "LOJA FECHADA", LED da vitrine apagado (desenho no topo), sem aberturas; potência mais baixa.
- [ ] **TV.6 — Degelo:** "Iniciar degelo por paragem".
  **Esperado:** modo "DEGELO", compressor parado, ventiladores ligados, o evaporador sobe devagar; termina entre 12 e 30 min simulados.
- [ ] **TV.7 — Porta à mão:** carregar em "Porta 2" e esperar mais de 2 min simulados.
  **Esperado:** P2 a laranja; alarme **PORTA ABERTA**. Fechar → o alarme desaparece.

## 3. Avarias

- [ ] **TV.8 — Condensador sujo** (60×).
  **Esperado:** a temperatura de condensação sobe; alarme **CONDENSACAO ALTA** (aos 50 °C); por volta dos 20 min simulados, **ALTA PRESSAO (PRESSOSTATO)** e o compressor para. "Rearmar pressostato" é recusado enquanto a avaria estiver ativa; depois de a remover e de a pressão baixar, rearma.
- [ ] **TV.9 — Porta mal fechada.**
  **Esperado:** P2 fica a laranja e aparece o evento "porta não fechou totalmente"; passados 2 min simulados (cerca de 25 s reais a 5×) surge **PORTA MAL FECHADA (P2)**, também na consola central. O funcionamento do compressor sobe; mais tarde surgem HACCP e **TEMPERATURA ALTA**.
- [ ] **TV.10 — Fuga de R290.**
  **Esperado:** **CARGA DE R290 BAIXA**; aspiração mais baixa e superaquecimento acima de 15 K; a temperatura sobe ao longo de horas simuladas.
- [ ] **TV.11 — Ventilador do evaporador.**
  **Esperado:** ventiladores "AVARIA"; o evaporador desce abaixo de −10 °C (gelo); o ar aquece.
- [ ] **TV.12 — Anti-embaciamento:** pôr a humidade a 75 % e ativar a avaria.
  **Esperado:** resistência a 0 %; "Vidros das portas" passa a "A embaciar" e depois a **VIDROS EMBACIADOS**. Remover a avaria → os vidros limpam.
- [ ] **TV.13 — Iluminação LED** (com a loja aberta).
  **Esperado:** **FALHA DE ILUMINACAO**; potência cerca de 54 W mais baixa.
- [ ] **TV.14 — Falha de energia.**
  **Esperado:** modo "SEM ENERGIA", 0 V e 0 W, tudo parado; a temperatura do ar sobe e, mais tarde, a do produto (HACCP).
- [ ] **TV.15 — Reiniciar:** "Reiniciar".
  **Esperado:** a simulação volta às 07:20 sem avarias; a velocidade mantém-se.

## 4. MQTT e consola

- [ ] **TV.16 — Broker:** `mosquitto_sub -h 192.168.68.123 -t 'pt/norte/porto-boavista/lacticinios/vt-01/#' -v`
  **Esperado:** `status online` e `state` de 5 em 5 s, com `"type": "vitrine"`.
- [ ] **TV.17 — Consola:** abrir `http://192.168.68.123:8090/`.
  **Esperado:** a VT-01 aparece ao lado da CF-01 e das câmaras de exemplo; temperatura, compressor, portas e alarmes coerentes com a página do ESP32.
- [ ] **TV.18 — Last will:** desligar o USB do ESP32.
  **Esperado:** passados cerca de 30 s, a consola mostra a VT-01 offline.

## 5. Bluetooth

- [ ] **TV.19 — Visível:** `py desktop\vitrine_ble.py scan` nos primeiros 3 min.
  **Esperado:** `Vitrine-VT-01` na lista.
- [ ] **TV.20 — Estado:** `py desktop\vitrine_ble.py vitrine status`.
  **Esperado:** `device ESP32-S3`, rede, IP e `mqtt_connected True`.
- [ ] **TV.21 — Botão BOOT:** depois de a janela fechar (LED apagado), premir BOOT durante 1 s.
  **Esperado:** o LED RGB volta a ficar azul e `Vitrine-VT-01` aparece outra vez no `scan` durante 5 min.
- [ ] **TV.22 — Redes:** `vitrine add --ssid "Teste" --mqtt-host 10.0.0.5`, depois `vitrine list` e `vitrine remove --ssid "Teste"`.
  **Esperado:** a rede aparece com `origem: ble` e depois desaparece.

## 6. Testes automáticos no PC

```powershell
py tests/test_simulator.py
```

**Esperado:** a linha `OK: ...` (controlo normal, horário, degelo por paragem, pressostato, fuga de R290, porta mal fechada, vidros embaciados, porta aberta, falha de energia e validação de comandos).

## Registo de resultados

| Data | Teste | Resultado | Notas |
|---|---|---|---|
| | | | |
