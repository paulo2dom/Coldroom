# Configuracao da Vitrine SIM no ESP32-S3 Supermini (raiz do ESP32). Nao partilhar.
WIFI_SSID = 'my_home'
WIFI_PASSWORD = 'Tsuki!2019'
DEVICE_NAME = 'Vitrine-SIM-01'    # id MQTT: unico no broker
HTTP_PORT = 80
# MQTT (apagar MQTT_HOST para desativar)
MQTT_HOST = '192.168.68.123'
MQTT_PORT = 1883
MQTT_USER = None       # ex.: 'utilizador' se o Mosquitto pedir autenticacao
MQTT_PASSWORD = None
# Localizacao do equipamento -> topico MQTT: pais/zona/loja/local/equipamento
LOCATION_COUNTRY = 'pt'              # pais
LOCATION_ZONE = 'norte'              # zona / regiao
LOCATION_STORE = 'porto-boavista'    # loja
LOCATION_AREA = 'lacticinios'        # localizacao dentro da loja
LOCATION_EQUIPMENT = 'vt-01'         # equipamento
MQTT_INTERVAL = 5      # segundos reais entre publicacoes

# --- Redes Wi-Fi conhecidas ------------------------------------------------------
# O ESP32 liga-se a rede conhecida com melhor sinal. 'mqtt_host' = IP do Raspberry Pi
# (broker) NESSA rede (se faltar usa MQTT_HOST). Tambem se podem adicionar redes por
# Bluetooth (ficam em networks.json no ESP32):
#   py desktop/vitrine_ble.py vitrine add ...
WIFI_NETWORKS = [
    {'ssid': WIFI_SSID, 'password': WIFI_PASSWORD, 'mqtt_host': MQTT_HOST, 'priority': 1},
    {'ssid': 'NOS_Internet_0D19', 'password': '35045546', 'mqtt_host': '10.33.33.15',
     'ip': '10.33.33.17/24', 'gw': '10.33.33.1', 'priority': 2},  # rede NOS (preferida): IPs fixos (Pi .15, Pico .16, ESP32 .17)
    # {'ssid': 'OutraRede', 'password': 'password123', 'mqtt_host': '192.168.1.50'},
]

# --- Bluetooth (configuracao de redes) -------------------------------------------
BLE_BOOT_WINDOW_S = 180   # BLE ativo durante 3 min apos cada arranque
BLE_WINDOW_S = 300        # sem Wi-Fi conhecido ou botao BOOT premido 1 s: 5 min


# --- Hardware (ESP32-S3 Supermini) ------------------------------------------------
LED_PIN = 48      # LED da placa
LED_RGB = True    # LED RGB WS2812 no GPIO48 (testado); False = LED simples
BUTTON_PIN = 0    # botao BOOT
