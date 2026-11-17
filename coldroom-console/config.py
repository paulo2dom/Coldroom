# ---------------------------------------------------------------------------
# ColdRoom · Consola central — configuração
# Corre no Raspberry Pi Zero 2 W. Edita e reinicia o serviço:
#   sudo systemctl restart coldroom-console
# ---------------------------------------------------------------------------

# Nome que aparece no topo da consola e no separador do browser
CONSOLE_NAME = "Consola central"

# --- Broker MQTT (Mosquitto) ----------------------------------------------
# Apaga ou comenta MQTT_HOST para desativar o MQTT (a consola mostra
# "MQTT DESATIVADO").
MQTT_HOST = "127.0.0.1"        # o Mosquitto corre neste mesmo Pi (192.168.68.123)
MQTT_PORT = 1883
MQTT_USER = None            # ex.: "consola"
MQTT_PASSWORD = None        # ex.: "segredo"
MQTT_CLIENT_ID = "coldroom-console"
MQTT_KEEPALIVE = 15         # s — define quão depressa se deteta a queda do broker

# TLS (porta 8883). Deixa MQTT_TLS = False para ligação simples.
MQTT_TLS = False
MQTT_CA_FILE = None         # ex.: "/etc/mosquitto/ca_certificates/ca.crt"

# Tópicos: pais/zona/loja/local/equipamento/state
# '+' apanha qualquer nível. Podes restringir, ex.: "pt/norte/+/+/+/state"
MQTT_TOPICS = [
    "+/+/+/+/+/state",
    "+/+/+/+/+/status",     # opcional: LWT "online"/"offline" do equipamento
]

# --- Servidor web -----------------------------------------------------------
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8090            # a 8080 ja e usada pelo Mosquitto (WebSockets) neste Pi

# Autenticação básica opcional (recomendado se a rede não for de confiança)
HTTP_USER = None            # ex.: "admin"
HTTP_PASSWORD = None

# --- Comportamento ----------------------------------------------------------
# Sem mensagens há mais de N segundos → câmara "SEM COMUNICAÇÃO" (gera alarme)
STALE_AFTER_S = 60

# Histórico de tendência guardado em memória por câmara
HISTORY_INTERVAL_S = 10     # 1 ponto a cada 10 s
HISTORY_POINTS = 720        # 720 × 10 s = 2 horas

# Alarme calculado pela consola quando a temperatura da câmara ultrapassa
# setpoint + TEMP_HIGH_DELTA durante mais de TEMP_HIGH_DELAY_S.
# Põe TEMP_HIGH_DELTA = None para usar só os alarmes enviados pelos equipamentos.
TEMP_HIGH_DELTA = 3.0
TEMP_HIGH_DELAY_S = 300

# Eventos (início/fim de alarmes) guardados em memória
EVENT_LOG_SIZE = 300

# --- Câmaras de exemplo -------------------------------------------------------
# Publicadas no Mosquitto pelo serviço coldroom-examples (coldroom_examples.py),
# cada uma com ligação MQTT própria, como se fossem Picos W. Aparecem com
# "(exemplo)" no nome. A CF-01 é o Pico W real. Para as remover, deixa a lista
# vazia (EXAMPLE_DEVICES = []) e: sudo systemctl restart coldroom-examples
# Formato: ("pais/zona/loja/local/equipamento", setpoint em °C)
EXAMPLE_DEVICES = [
    ("pt/norte/porto-boavista/peixaria/cf-02", 0.0),
    ("pt/norte/porto-boavista/congelados/cf-03", -20.0),
    ("pt/norte/braga-centro/talho/cf-04", 2.0),
    ("pt/centro/coimbra-baixa/lacticinios/cf-05", 4.0),
    ("pt/sul/lisboa-colombo/frutas-e-legumes/cf-06", 6.0),
]
