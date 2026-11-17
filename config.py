# Copia este ficheiro para config.py (na raiz do Pico W).
WIFI_SSID = 'my_home'
WIFI_PASSWORD = 'Tsuki!2019'
DEVICE_NAME = 'ColdRoom-SIM-01'
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
LOCATION_AREA = 'talho'              # localizacao dentro da loja
LOCATION_EQUIPMENT = 'cf-01'         # equipamento
MQTT_INTERVAL = 5      # segundos reais entre publicacoes

# --- Redes Wi-Fi conhecidas ------------------------------------------------------
# O Pico liga-se a rede conhecida com melhor sinal. 'mqtt_host' = IP do Raspberry Pi
# (broker) NESSA rede (se faltar usa MQTT_HOST). Tambem se podem adicionar redes por
# Bluetooth (ficam em networks.json no Pico): py desktop/coldroom_ble.py pico add ...
WIFI_NETWORKS = [
    {'ssid': WIFI_SSID, 'password': WIFI_PASSWORD, 'mqtt_host': MQTT_HOST},
    {'ssid': 'NOS_Internet_0D19', 'password': '35045546', 'mqtt_host': None},  # rede do config antigo (05/11)
    # {'ssid': 'OutraRede', 'password': 'password123', 'mqtt_host': '192.168.1.50'},
]

# --- Bluetooth (configuracao de redes) -------------------------------------------
BLE_BOOT_WINDOW_S = 180   # BLE ativo durante 3 min apos cada arranque
BLE_WINDOW_S = 300        # sem Wi-Fi conhecido ou BOOTSEL premido 1 s: 5 min
