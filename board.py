"""Diferencas de hardware entre placas (o resto do codigo e igual).

  Pico W (RP2040)        : LED da placa ('LED'), botao BOOTSEL
  ESP32-S3 Supermini     : LED RGB WS2812 no GPIO48, botao BOOT no GPIO0

Opcional no config.py: LED_PIN, LED_RGB (True = WS2812), BUTTON_PIN.
"""
import sys
import machine

try:
    import config
except ImportError:
    config = None


def _cfg(name, default):
    return getattr(config, name, default) if config else default


PLATFORM = sys.platform          # 'rp2' ou 'esp32'

if PLATFORM == 'rp2':
    import rp2
    NAME = 'Pico W'
    BUTTON_NAME = 'BOOTSEL'
    _led = machine.Pin(_cfg('LED_PIN', 'LED'), machine.Pin.OUT)
    _rgb = None

    def button():
        return bool(rp2.bootsel_button())
else:
    NAME = 'ESP32-S3'
    BUTTON_NAME = 'BOOT'
    _btn = machine.Pin(_cfg('BUTTON_PIN', 0), machine.Pin.IN, machine.Pin.PULL_UP)
    if _cfg('LED_RGB', True):
        import neopixel
        _rgb = neopixel.NeoPixel(machine.Pin(_cfg('LED_PIN', 48)), 1)
        _led = None
    else:
        _rgb = None
        _led = machine.Pin(_cfg('LED_PIN', 48), machine.Pin.OUT)

    def button():
        return _btn.value() == 0


_led_state = None


def led(on):
    """LED aceso = Bluetooth ativo (no WS2812: azul fraco)."""
    global _led_state
    on = bool(on)
    if on == _led_state:
        return
    _led_state = on
    if _rgb is not None:
        _rgb[0] = (0, 0, 40) if on else (0, 0, 0)
        _rgb.write()
    else:
        _led.value(1 if on else 0)
