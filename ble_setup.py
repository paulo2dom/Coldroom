"""Configuracao por Bluetooth LE (Pico W / MicroPython), baseada no PicoPulse.

Protocolo (igual no Raspberry Pi, ver coldroom-console/coldroom_ble.py):
  - escrever na caracteristica RX: b'B' (inicio), b'D'+<ate 19 bytes> (dados), b'E' (fim)
    os dados formam um JSON, ex.: {"cmd": "list"}
  - ler a caracteristica STATUS: 'READY', 'BUSY' ou a resposta JSON '{...}'

AVISO (laboratorio): no MicroPython RP2 a ligacao BLE NAO e cifrada; as passwords
Wi-Fi passam em claro. O BLE so fica ativo durante janelas curtas.
"""
import bluetooth
import json
import time

SERVICE_UUID = "7C0D1A50-2B6E-4C1F-9E31-C01D500A0001"
RX_UUID = "7C0D1A50-2B6E-4C1F-9E31-C01D500A0002"
STATUS_UUID = "7C0D1A50-2B6E-4C1F-9E31-C01D500A0003"

_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3
_FLAG_READ = 0x0002
_FLAG_WRITE_NO_RESPONSE = 0x0004
_FLAG_WRITE = 0x0008
_MAX_CMD = 512


def _adv_payload(name):
    n = name.encode()[:26]
    return b"\x02\x01\x06" + bytes((len(n) + 1, 0x09)) + n


class BLESetup:
    def __init__(self, name):
        self.name = name
        self.ble = None
        self.enabled = False
        self.deadline = 0
        self.connected = set()
        self.buffer = bytearray()
        self.receiving = False
        self.pending = None

    # --- janela de configuracao -------------------------------------------
    def start(self, seconds):
        if not self.enabled:
            self.ble = bluetooth.BLE()
            self.ble.active(True)
            svc = (bluetooth.UUID(SERVICE_UUID), (
                (bluetooth.UUID(RX_UUID), _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE),
                (bluetooth.UUID(STATUS_UUID), _FLAG_READ),
            ))
            ((self.rx, self.st),) = self.ble.gatts_register_services((svc,))
            self.ble.gatts_set_buffer(self.rx, 32)
            self.ble.gatts_set_buffer(self.st, _MAX_CMD)
            self.ble.irq(self._irq)
            self.enabled = True
            self._status("READY")
            self._advertise()
        self.deadline = time.ticks_add(time.ticks_ms(), seconds * 1000)
        print("BLE: '%s' ativo durante %d s" % (self.name, seconds))

    def stop(self):
        if not self.enabled:
            return
        self.enabled = False
        try:
            self.ble.gap_advertise(None)
            for c in tuple(self.connected):
                self.ble.gap_disconnect(c)
            self.ble.active(False)
        except OSError:
            pass
        self.connected = set()
        print("BLE: desativado")

    def remaining_s(self):
        if not self.enabled:
            return 0
        return max(0, time.ticks_diff(self.deadline, time.ticks_ms()) // 1000)

    def _advertise(self):
        self.ble.gap_advertise(100_000, adv_data=_adv_payload(self.name))

    def _status(self, text):
        self.ble.gatts_write(self.st, text.encode()[:_MAX_CMD])

    # --- eventos BLE (IRQ: so copiar dados; processar no ciclo principal) ---
    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.connected.add(data[0])
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.connected.discard(data[0])
            self.receiving = False
            if self.enabled:
                self._advertise()
        elif event == _IRQ_GATTS_WRITE and data[1] == self.rx and self.pending is None:
            pkt = self.ble.gatts_read(self.rx)
            if pkt == b"B":
                self.buffer = bytearray()
                self.receiving = True
                self._status("BUSY")
            elif pkt[:1] == b"D" and self.receiving:
                if len(self.buffer) + len(pkt) - 1 > _MAX_CMD:
                    self.receiving = False
                    self._status('{"ok":false,"error":"comando demasiado longo"}')
                else:
                    self.buffer.extend(pkt[1:])
            elif pkt == b"E" and self.receiving:
                self.receiving = False
                self.pending = bytes(self.buffer)
            else:
                self._status('{"ok":false,"error":"protocolo"}')

    def poll(self):
        """Devolve o proximo comando (dict) ou None. Fecha a janela quando expira."""
        if self.enabled and time.ticks_diff(self.deadline, time.ticks_ms()) <= 0 and not self.connected:
            self.stop()
        if self.pending is None:
            return None
        raw, self.pending = self.pending, None
        try:
            cmd = json.loads(raw.decode())
            if not isinstance(cmd, dict):
                raise ValueError
            return cmd
        except (ValueError, UnicodeError):
            self.reply({"ok": False, "error": "JSON invalido"})
            return None

    def reply(self, obj):
        if self.enabled:
            self._status(json.dumps(obj))
