"""Hardware do ESP32-S3 Supermini: LED RGB WS2812 (GPIO48) e botao BOOT (GPIO0).

Opcional no config.py: LED_PIN, LED_RGB (False = LED simples), BUTTON_PIN.
"""
import machine

try:
    import config
except ImportError:
    config = None

NAME = 'ESP32-S3'
BUTTON_NAME = 'BOOT'


def _cfg(name, default):
    return getattr(config, name, default) if config else default


_btn = machine.Pin(_cfg('BUTTON_PIN', 0), machine.Pin.IN, machine.Pin.PULL_UP)
if _cfg('LED_RGB', True):
    import neopixel
    _rgb = neopixel.NeoPixel(machine.Pin(_cfg('LED_PIN', 48)), 1)
    _led = None
else:
    _rgb = None
    _led = machine.Pin(_cfg('LED_PIN', 48), machine.Pin.OUT)

_state = None


def button():
    """True enquanto o botao BOOT esta premido."""
    return _btn.value() == 0


def led(on):
    """LED aceso = Bluetooth ativo (no WS2812: azul fraco)."""
    global _state
    on = bool(on)
    if on == _state:
        return
    _state = on
    if _rgb is not None:
        _rgb[0] = (0, 0, 40) if on else (0, 0, 0)
        _rgb.write()
    else:
        _led.value(1 if on else 0)
