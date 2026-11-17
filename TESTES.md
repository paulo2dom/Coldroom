# Plano de testes — ColdRoom SIM (Pico W)

Ações de teste para validar o simulador da câmara frigorífica **CF-01** a correr no Pico W.
Os valores esperados foram obtidos a correr o próprio `simulator.py` no PC; no Pico podem variar ligeiramente (o passo de tempo depende da velocidade do ciclo), por isso são **aproximados**.

---

## 0. Preparação

| Item | Valor |
|---|---|
| Dashboard | `http://192.168.68.116/` (confirmar IP no router se mudar) |
| API | `GET /api/state`, `POST /api/action` |
| Consola série | `py -m mpremote connect COM7` (fechar o MicroPico no VS Code antes) |
| Valores iniciais | Setpoint 2,0 °C · Ambiente 24 °C · Câmara 4,7 °C · Velocidade 5× |

**Antes de cada grupo de testes:** carregar em **Reiniciar** (repõe tudo, incluindo velocidade 5×) e depois escolher **20×** para acelerar.

### Conversão de tempo (tempo simulado → tempo real)

| Tempo simulado | a 1× | a 5× | a 20× |
|---|---|---|---|
| 1 min | 1 min | 12 s | 3 s |
| 4 min (degelo) | 4 min | 48 s | 12 s |
| 10 min | 10 min | 2 min | 30 s |
| 30 min | 30 min | 6 min | 1,5 min |
| 6 h (degelo automático) | 6 h | 72 min | 18 min |

O relógio no topo do dashboard ("Tempo virtual") mostra o tempo simulado.

---

## 1. Arranque e ligação

- [ ] **T1.1 — Arranque automático**
  Desligar e voltar a ligar o USB do Pico. Esperar ~10 s e abrir o dashboard.
  **Esperado:** página carrega; indicador **● SIMULADOR ONLINE** (verde); evento "Simulador inicializado; dados inteiramente ficticios".

- [ ] **T1.2 — Perda de ligação**
  Com o dashboard aberto, desligar o USB do Pico.
  **Esperado:** em ≤ 4 s o indicador passa a **● SEM LIGAÇÃO** (vermelho). Ao voltar a ligar, regressa a ONLINE sozinho (sem recarregar a página).

- [ ] **T1.3 — Estado perdido após reinício**
  Alterar o setpoint, reiniciar o Pico (desligar/ligar USB).
  **Esperado:** volta tudo aos valores iniciais (histórico e eventos estão só em RAM).

- [ ] **T1.4 — Vários clientes**
  Abrir o dashboard no PC e no telemóvel ao mesmo tempo. Abrir a porta num deles.
  **Esperado:** o outro mostra a porta aberta na atualização seguinte (~2 s).

---

## 2. Funcionamento normal (controlo por histerese)

- [ ] **T2.1 — Arranque do compressor**
  Após Reiniciar (câmara a 4,7 °C, setpoint 2,0 °C).
  **Esperado:** compressor **liga** logo (câmara > setpoint + 0,6 °C); capacidade sobe; válvula de expansão abre; pressão de aspiração desce.

- [ ] **T2.2 — Descida até ao setpoint** (≈10 min simulados = 30 s a 20×)
  **Esperado:** câmara ≈ 1,5 °C, compressor ≈ 40 %, potência ≈ 2 kW, corrente ≈ 3,3 A.

- [ ] **T2.3 — Banda de histerese** (deixar correr 1 h simulada = 3 min a 20×)
  **Esperado:** câmara oscila entre **≈ 1,4 °C e ≈ 2,6 °C** (setpoint ± 0,6). Compressor desliga abaixo de 1,4 e liga acima de 2,6.
  Com compressor parado: potência ≈ 0,18 kW (só ventiladores), pressão de descarga ≈ 7,8 bar, aspiração ≈ 2,5 bar.

- [ ] **T2.4 — Gráfico de histórico**
  **Esperado:** um ponto a cada 30 s simulados; 3 curvas (câmara, insuflação, retorno). Máximo 80 pontos (= últimos 40 min simulados); os mais antigos vão saindo.

- [ ] **T2.5 — Contadores**
  Deixar correr alguns minutos.
  **Esperado:** energia (kWh), horas de compressor e horas de ventiladores só **aumentam**; horas de compressor param quando o compressor está desligado.

- [ ] **T2.6 — Tensão**
  **Esperado:** tensão ≈ 400 V com pequena oscilação (± 2,5 V).

---

## 3. Porta aberta / fechada

- [ ] **T3.1 — Abrir porta** (ambiente 24 °C)
  Carregar em **Abrir porta**.
  **Esperado:** alarme **PORTA ABERTA**; evento WARN "Porta aberta"; botão passa a "Fechar porta"; ar de retorno ≈ câmara + 0,8 °C (com porta fechada é + 0,3 °C).

- [ ] **T3.2 — Porta aberta 20 min simulados** (1 min real a 20×)
  **Esperado:** câmara sobe lentamente até ≈ 3,9 °C; compressor a trabalhar contínuo a ≈ 65–70 %; potência ≈ 2,9 kW.

- [ ] **T3.3 — Fechar porta**
  **Esperado:** alarme desaparece; evento INFO "Porta fechada"; câmara volta a ≈ 2 °C em 5–15 min simulados e retoma a histerese.

- [ ] **T3.4 — Pior caso: porta aberta com ambiente 40 °C**
  Ambiente = 40 → Aplicar; abrir porta; 30 min simulados.
  **Esperado:** câmara sobe para ≈ 8 °C; compressor a **100 %**; pressão de descarga ≈ 16,7 bar; potência ≈ 4 kW.

---

## 4. Setpoint e temperatura ambiente

- [ ] **T4.1 — Setpoint de congelação**
  Setpoint = −18 → Aplicar.
  **Esperado:** evento "Setpoint alterado para -18.0 C"; compressor a 100 %; câmara ≈ −13,5 °C aos 30 min e ≈ −18 °C aos 60 min simulados; pressão de aspiração desce mas **nunca abaixo de 0,2 bar**.

- [ ] **T4.2 — Setpoint alto**
  Setpoint = 12 → Aplicar.
  **Esperado:** compressor desliga; câmara sobe **muito devagar** (só por ganho térmico passivo; ≈ 3,9 °C após 30 min simulados).

- [ ] **T4.3 — Ambiente quente com porta fechada**
  Ambiente = 40 → Aplicar; 60 min simulados.
  **Esperado:** câmara continua controlada (≈ 1,5–2,6 °C); pressão de descarga sobe para ≈ 15 bar.

- [ ] **T4.4 — Limites do setpoint** (valores inválidos)
  Tentar **13** e **−19**.
  **Esperado:** mensagem "Setpoint permitido: -18 a 12 C"; setpoint não muda.
  Tentar **12** e **−18** (limites): aceites.

- [ ] **T4.5 — Limites do ambiente**
  Tentar **14** e **41** → mensagem "Ambiente permitido: 15 a 40 C". **15** e **40** são aceites.

---

## 5. Degelo

- [ ] **T5.1 — Degelo manual**
  Carregar em **Iniciar degelo**.
  **Esperado:** evento "Ciclo de degelo iniciado"; compressor **desliga**; ventiladores **desligam**; evaporador sobe para ≈ 6,5 °C; potência ≈ 2,2 kW (resistência de degelo); câmara aquece um pouco.

- [ ] **T5.2 — Fim do degelo**
  **Esperado:** termina sozinho ao fim de **≈ 4 min simulados** (12 s a 20×) ou quando o evaporador passa 8 °C; evento "Ciclo de degelo terminado"; ventiladores e compressor retomam.

- [ ] **T5.3 — Carregar duas vezes em degelo**
  Iniciar degelo e voltar a carregar durante o ciclo.
  **Esperado:** sem efeito (não reinicia o contador nem cria evento novo).

- [ ] **T5.4 — Degelo automático**
  Deixar correr 6 h simuladas (18 min a 20×) sem degelo manual.
  **Esperado:** degelo inicia sozinho. (Um degelo manual reinicia a contagem das 6 h.)

---

## 6. Avarias e proteção

Para cada avaria: ativar → observar → tentar rearmar → remover → rearmar.

- [ ] **T6.1 — Falha de fase**
  **Esperado:** alarmes **FALHA DE FASE** + **COMPRESSOR BLOQUEADO**; evento ALARM "Protecao de seguranca: compressor bloqueado"; tensão **0 V**; corrente 0; ventiladores **desligados**; potência 0.

- [ ] **T6.1b — Falha de fase durante o degelo**
  Iniciar degelo e, durante o ciclo, ativar falha de fase.
  **Esperado:** tensão, corrente e potência **todas a 0** (a resistência de degelo fica sem alimentação); evaporador e câmara deixam de aquecer pela resistência.

- [ ] **T6.2 — Óleo baixo**
  **Esperado:** **NIVEL DE OLEO BAIXO** + **COMPRESSOR BLOQUEADO**; compressor parado; ventiladores continuam (≈ 0,18 kW).

- [ ] **T6.3 — Alta pressão**
  **Esperado:** **ALTA PRESSAO** + **COMPRESSOR BLOQUEADO**; pressão de descarga sobe para ≈ 19 bar em 10 s, ≈ 24 bar em 30 s e estabiliza em **25 bar** (tempos simulados).

- [ ] **T6.4 — Rearmar com avaria ativa** (para T6.1–T6.3)
  Carregar em **Rearmar proteção** com a avaria ainda ativa.
  **Esperado:** recusado com "Remove primeiro as avarias ativas".

- [ ] **T6.5 — Bloqueio mantém-se depois de remover a avaria** (latched)
  Desativar a avaria **sem** rearmar.
  **Esperado:** alarme da avaria desaparece mas **COMPRESSOR BLOQUEADO** mantém-se; compressor continua parado; a câmara vai aquecendo.

- [ ] **T6.6 — Rearmar**
  Carregar em **Rearmar proteção**.
  **Esperado:** evento "Protecao rearmada"; bloqueio desaparece; compressor volta a ligar se a câmara estiver acima de setpoint + 0,6.

- [ ] **T6.7 — Refrigerante baixo** (não bloqueia)
  **Esperado:** alarme **REFRIGERANTE BAIXO** mas **sem** bloqueio; capacidade máxima limitada a **45 %**; aspiração ≈ 0,7 bar mais baixa (mínimo 0,2 bar); superaquecimento +4 K; subarrefecimento −3,5 K; o compressor trabalha mais tempo para chegar ao setpoint.

- [ ] **T6.8 — Refrigerante baixo + ambiente 40 °C + porta aberta**
  **Esperado:** o sistema **não consegue** manter a temperatura: câmara ≈ 8 °C aos 10 min, ≈ 15 °C aos 30 min, ≈ 22 °C aos 60 min simulados; compressor fixo em 45 %. Com a câmara acima de setpoint + 4 °C durante 10 min simulados aparece **TEMPERATURA ALTA**.

- [ ] **T6.8b — Temperatura alta por paragem do compressor**
  Ativar a falha de fase e deixar correr (20× acelera).
  **Esperado:** ao fim de cerca de 70 min simulados aparece **TEMPERATURA ALTA**, no Pico e na consola central. Remover a avaria e rearmar → a câmara arrefece e o alarme desaparece quando volta abaixo de setpoint + 4 °C.

- [ ] **T6.9 — Várias avarias ao mesmo tempo**
  Ativar fase + óleo. Remover só uma e tentar rearmar.
  **Esperado:** rearme recusado enquanto houver uma avaria de proteção ativa.

---

## 7. Velocidade e reinício

- [ ] **T7.1 — Velocidades 1×, 5×, 20×**
  **Esperado:** o relógio virtual avança à velocidade escolhida; o texto "Velocidade" atualiza.

- [ ] **T7.2 — Reiniciar**
  Com porta aberta, avarias e setpoint alterado, carregar em **Reiniciar** e confirmar.
  **Esperado:** pede confirmação; tudo volta aos valores iniciais (incluindo velocidade **5×**); histórico e eventos limpos.

- [ ] **T7.3 — Lista de eventos**
  Abrir/fechar a porta 15 vezes seguidas.
  **Esperado:** só ficam os **12 eventos** mais recentes, o mais novo em cima.

---

## 8. Testes à API (PowerShell no PC)

Definir uma vez por sessão:

```powershell
$pico = "http://192.168.68.116"
function Send-Sim($body) {
  try {
    Invoke-RestMethod -Method Post -Uri "$pico/api/action" -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress)
  } catch { "ERRO: " + $_.ErrorDetails.Message }
}
```

| # | Comando | Esperado |
|---|---|---|
| T8.1 | `Invoke-RestMethod "$pico/api/state"` | JSON com `simulated: True`, `room`, `alarms`, `history`… |
| T8.2 | `Send-Sim @{action='door'; value=$true}` | `ok: True`; dashboard mostra porta aberta |
| T8.3 | `Send-Sim @{action='setpoint'; value=-5}` | `ok: True` |
| T8.4 | `Send-Sim @{action='setpoint'; value=20}` | `ERRO: {"error": "Setpoint permitido: -18 a 12 C"}` |
| T8.5 | `Send-Sim @{action='ambient'; value=50}` | `ERRO: … Ambiente permitido: 15 a 40 C` |
| T8.6 | `Send-Sim @{action='speed'; value=3}` | `ERRO: … Velocidade invalida` |
| T8.7 | `Send-Sim @{action='fault'; name='xyz'; value=$true}` | `ERRO: … Avaria desconhecida` |
| T8.8 | `Send-Sim @{action='voar'}` | `ERRO: … Acao nao suportada` |
| T8.9 | `Send-Sim @{action='setpoint'; value='abc'}` | `ERRO: … Setpoint invalido` |
| T8.10 | `Send-Sim @{action='setpoint'; value=2; lixo=('x'*600)}` | `ERRO: … Tamanho invalido` (corpo > 512 bytes) |
| T8.11 | `Invoke-RestMethod "$pico/naoexiste"` | Erro 404 `endpoint inexistente` |
| T8.12 | `Send-Sim @{action='fault'; name='hp_fault'; value=$true}` e depois `Send-Sim @{action='reset'}` | `ERRO: … Remove primeiro as avarias ativas` |
| T8.13 | `Send-Sim @{action='restart'}` | `ok: True`; tudo reposto |

- [ ] **T8.14 — Estabilidade com pedidos repetidos**
  ```powershell
  1..200 | % { $null = Invoke-RestMethod "$pico/api/state" }; "OK"
  ```
  **Esperado:** termina sem erros; o dashboard continua a responder; na consola série não aparecem `Erro HTTP` em série nem `MemoryError`.

---

## 8b. MQTT (Mosquitto em 192.168.68.123)

Numa máquina com o cliente Mosquitto (por exemplo, o próprio servidor):

```bash
mosquitto_sub -h 192.168.68.123 -t 'pt/norte/porto-boavista/talho/cf-01/#' -v
```

- [ ] **TM.1 — Publicação periódica**
  **Esperado:** `pt/norte/porto-boavista/talho/cf-01/status online` e uma mensagem `pt/norte/porto-boavista/talho/cf-01/state` com JSON a cada ~5 s; o `sim_seconds` vai aumentando; o JSON inclui `location` com país, zona, loja, local e equipamento.

- [ ] **TM.2 — Mensagens retidas**
  Parar e voltar a lançar o `mosquitto_sub`.
  **Esperado:** recebe logo o último `state` e o `status` (retidos), sem esperar 5 s.

- [ ] **TM.3 — Alterações refletidas**
  Abrir a porta no dashboard.
  **Esperado:** na mensagem seguinte `"door": true` e `"alarms": ["PORTA ABERTA"]`.

- [ ] **TM.4 — Pico desligado (last will)**
  Desligar o USB do Pico.
  **Esperado:** passados ~45 s aparece `pt/norte/porto-boavista/talho/cf-01/status offline`.

- [ ] **TM.5 — Broker em baixo**
  Parar o Mosquitto (`sudo systemctl stop mosquitto`) com o Pico a correr.
  **Esperado:** dashboard continua a funcionar normalmente; na consola série aparece `MQTT erro:` de 15 em 15 s.
  Voltar a arrancar o Mosquitto → em ≤ 15 s aparece `MQTT ligado a 192.168.68.123` e as mensagens retomam.

- [ ] **TM.5b — Filtros por nível**
  `mosquitto_sub -h 192.168.68.123 -t 'pt/+/+/talho/+/state' -v`
  **Esperado:** recebe as mensagens da CF-01. Com `-t 'pt/sul/#'` não recebe nada.

- [ ] **TM.5c — Mudar a localização**
  No `config.py` mudar `LOCATION_STORE = 'Lisboa Colombo'`, enviar e reiniciar.
  **Esperado:** passa a publicar em `pt/norte/lisboa-colombo/talho/cf-01/...` (minúsculas, espaço → `-`).

- [ ] **TM.5d — Localização e MQTT no dashboard**
  Abrir o dashboard.
  **Esperado:** título "Câmara frigorífica **CF-01**"; etiquetas `PAÍS PT › ZONA Norte › LOJA Porto Boavista › LOCAL Talho`; linha "Tópico MQTT: pt/norte/porto-boavista/talho/cf-01/state"; no topo **● MQTT LIGADO** (verde). Separador do browser: "ColdRoom | CF-01 · Porto Boavista".
  Parar o Mosquitto → em ~5–15 s (só é detetado na publicação seguinte que falhar) passa a **● MQTT SEM LIGAÇÃO** (laranja) e volta a verde quando o broker regressar.

- [ ] **TM.6 — Desativar MQTT**
  Apagar a linha `MQTT_HOST` do `config.py`, enviar e reiniciar.
  **Esperado:** sem mensagens no broker; simulador e dashboard normais; no topo aparece **MQTT DESATIVADO**.

---

## 8c. Redes e Bluetooth

- [ ] **TB.1 — Equipamentos visíveis:** `py desktop\coldroom_ble.py scan` logo após arrancar o Pico.
  **Esperado:** `ColdRoom-CF-01` e (nos primeiros 10 min do Pi) `ColdRoom-Pi`. LED do Pico aceso.
- [ ] **TB.2 — Janela do Pico fecha:** 3 min após arrancar.
  **Esperado:** LED apaga; `scan` deixa de mostrar o Pico; simulador e MQTT continuam.
- [ ] **TB.3 — BOOTSEL:** premir BOOTSEL 1 s com o Pico a correr.
  **Esperado:** LED acende; Pico volta a aparecer no `scan` durante 5 min.
- [ ] **TB.4 — Adicionar/remover rede no Pico:** `pico add --ssid "Teste" --mqtt-host 10.0.0.5`, `pico list`, `pico remove --ssid "Teste"`.
  **Esperado:** rede aparece com `origem: ble` e `broker 10.0.0.5`; depois desaparece.
- [ ] **TB.5 — Proteção no Pi:** `pi remove --ssid my_home`.
  **Esperado:** `ERRO: E a rede em uso; usa force para remover mesmo assim`.
- [ ] **TB.6 — Rede nova no Pi:** `pi add --ssid "Teste"` e `pi list`, depois `pi remove --ssid "Teste"`.
  **Esperado:** ligação SSH/consola não cai; a rede aparece e desaparece da lista.
- [ ] **TB.7 — Pico sem rede conhecida:** levar o Pico para longe da rede (ou remover a única rede e `pico apply`).
  **Esperado:** abre BLE 5 min e tenta de novo a cada 30 s; adicionar a rede por BLE e `pico apply` → volta a ligar.

## 9. Testes automáticos no PC

- [ ] **T9.1** — na pasta `Coldroom`: `py tests/test_simulator.py`
  **Esperado:** `OK: dinamica, eventos, alarme, bloqueio, reset, degelo, comandos, aspiracao e degelo sem fase`

- [ ] **T9.2** — `py desktop/preview.py` e abrir `http://127.0.0.1:8766`
  **Esperado:** o mesmo dashboard, a correr no PC (útil para testar alterações antes de enviar para o Pico).

---

## 10. Comportamentos a ter em conta (observados nos testes)

Não são necessariamente erros, mas convém saber ao avaliar os resultados:

1. **Mudar a temperatura ambiente não cria evento** (o setpoint cria).
2. **Refrigerante baixo não bloqueia** o compressor e o rearme é aceite com essa avaria ativa — é intencional no código (só fase, óleo e alta pressão bloqueiam).
3. A energia e as horas de funcionamento partem de valores fictícios (1254 kWh, 3217 h, 4802 h).
4. Todos os valores são **simulados**; não usar para HACCP nem diagnóstico real.

---

## Registo de resultados

| Data | Teste | Resultado (OK / Falha) | Observações |
|---|---|---|---|
| | | | |
| | | | |
| | | | |
