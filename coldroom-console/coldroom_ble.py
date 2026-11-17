#!/usr/bin/env python3
"""ColdRoom - configuracao das redes Wi-Fi do Raspberry Pi por Bluetooth LE.

Servico GATT 'ColdRoom-Pi' (BlueZ via D-Bus) com o mesmo protocolo do Pico W:
  - escrever em RX: b'B' (inicio), b'D'+<dados> (blocos), b'E' (fim) -> JSON
    {"cmd": "status" | "list" | "add" | "remove" | "apply", ...}
  - ler STATUS: 'READY', 'BUSY' ou a resposta JSON '{...}'
As redes sao geridas pelo wpa_supplicant (wpa_cli): adicionar/remover nao corta
a ligacao atual; 'apply' faz 'wpa_cli reconfigure'.

Janela BLE: BOOT_WINDOW_S apos o arranque e sempre que o wlan0 nao tem ligacao.
Fora da janela o servico GATT e o anuncio BLE sao removidos.

AVISO (laboratorio): a ligacao BLE nao e cifrada; a password passa em claro.
No Pi guarda-se apenas a PSK derivada (hex), nao a password em texto.
Corre como root (systemd: coldroom-ble.service). Requer python3-dbus e python3-gi.
"""
import hashlib
import json
import socket
import subprocess
import sys
import time

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

NAME = "ColdRoom-Pi"
IFACE = "wlan0"
BOOT_WINDOW_S = 600
CHECK_S = 5
# Intervalo de anuncio BLE (unidades de 0,625 ms). O BlueZ usa 1,28 s por omissao,
# o que faz o Windows perder muitos anuncios; 100-150 ms torna a descoberta rapida.
ADV_INTERVAL = (160, 240)
DEBUGFS = "/sys/kernel/debug/bluetooth/hci0/"

SERVICE_UUID = "7c0d1a50-2b6e-4c1f-9e31-c01d500a0001"
RX_UUID = "7c0d1a50-2b6e-4c1f-9e31-c01d500a0002"
STATUS_UUID = "7c0d1a50-2b6e-4c1f-9e31-c01d500a0003"

BLUEZ = "org.bluez"
DBUS_OM = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP = "org.freedesktop.DBus.Properties"
GATT_MANAGER = "org.bluez.GattManager1"
ADV_MANAGER = "org.bluez.LEAdvertisingManager1"
GATT_SERVICE = "org.bluez.GattService1"
GATT_CHRC = "org.bluez.GattCharacteristic1"
LE_ADV = "org.bluez.LEAdvertisement1"
BASE = "/org/coldroom"


def log(*a):
    print("[ble]", *a, flush=True)


# ---------------------------------------------------------------------------
# Wi-Fi (wpa_cli)
# ---------------------------------------------------------------------------
def wpa(*args):
    r = subprocess.run(["wpa_cli", "-i", IFACE] + [str(a) for a in args],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=10)
    return r.stdout.strip()


def wpa_ok(*args):
    out = wpa(*args)
    if out.splitlines()[-1:] != ["OK"]:
        raise RuntimeError("wpa_cli %s: %s" % (args[0], out))


def wifi_status():
    st = {}
    for line in wpa("status").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            st[k] = v
    return st


def wifi_connected():
    st = wifi_status()
    return st.get("wpa_state") == "COMPLETED" and bool(st.get("ip_address"))


def networks():
    out = []
    for line in wpa("list_networks").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            nid = parts[0]
            prio = wpa("get_network", nid, "priority")
            out.append({"id": int(nid), "ssid": parts[1],
                        "priority": int(prio) if prio.lstrip("-").isdigit() else 0,
                        "current": "[CURRENT]" in (parts[3] if len(parts) > 3 else "")})
    return out


def find_id(ssid):
    for n in networks():
        if n["ssid"] == ssid:
            return n
    return None


def add_network(ssid, password, priority=None):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
        raise ValueError("SSID invalido (1 a 32 bytes)")
    if not isinstance(password, str) or not (len(password) == 0 or 8 <= len(password.encode()) <= 63):
        raise ValueError("Password invalida (8 a 63 caracteres, ou vazia para rede aberta)")
    existing = find_id(ssid)
    nid = str(existing["id"]) if existing else wpa("add_network").splitlines()[-1]
    if not nid.isdigit():
        raise RuntimeError("wpa_cli add_network falhou: %s" % nid)
    wpa_ok("set_network", nid, "ssid", ssid.encode().hex())          # hex: sem problemas de aspas
    if password:
        psk = hashlib.pbkdf2_hmac("sha1", password.encode(), ssid.encode(), 4096, 32).hex()
        wpa_ok("set_network", nid, "psk", psk)                         # so a PSK derivada fica guardada
        wpa_ok("set_network", nid, "key_mgmt", "WPA-PSK")
    else:
        wpa_ok("set_network", nid, "key_mgmt", "NONE")
    if priority is not None:
        wpa_ok("set_network", nid, "priority", int(priority))
    wpa_ok("enable_network", nid)
    wpa_ok("save_config")
    return "atualizada" if existing else "adicionada"


def remove_network(ssid, force=False):
    n = find_id(ssid)
    if not n:
        raise ValueError("Rede desconhecida: %s" % ssid)
    if n["current"] and not force:
        raise ValueError("E a rede em uso; usa force para remover mesmo assim")
    wpa_ok("remove_network", n["id"])
    wpa_ok("save_config")


def handle(cmd):
    c = cmd.get("cmd")
    if c == "status":
        st = wifi_status()
        ip = st.get("ip_address")
        return {"ok": True, "device": "pi", "name": NAME, "hostname": socket.gethostname(),
                "ssid": st.get("ssid"), "ip": ip, "wifi": st.get("wpa_state"),
                "console": "http://%s:8090/" % ip if ip else None, "networks": len(networks())}
    if c == "list":
        return {"ok": True, "networks": [{"ssid": n["ssid"], "priority": n["priority"], "current": n["current"]}
                                         for n in networks()]}
    if c == "add":
        what = add_network(cmd.get("ssid"), cmd.get("password") or "", cmd.get("priority"))
        return {"ok": True, "msg": "Rede %s; a ligacao atual mantem-se (apply para reconfigurar)" % what}
    if c == "remove":
        remove_network(cmd.get("ssid"), bool(cmd.get("force")))
        return {"ok": True, "msg": "Rede removida"}
    if c == "apply":
        GLib.timeout_add(1500, lambda: (wpa("reconfigure"), False)[1])
        return {"ok": True, "msg": "wpa_cli reconfigure dentro de 1,5 s (o Pi pode mudar de rede/IP)"}
    return {"ok": False, "error": "comando desconhecido: %s" % c}


# ---------------------------------------------------------------------------
# GATT (BlueZ D-Bus)
# ---------------------------------------------------------------------------
class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = BASE
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    @dbus.service.method(DBUS_OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        resp = {}
        for s in self.services:
            resp[s.get_path()] = s.get_properties()
            for ch in s.characteristics:
                resp[ch.get_path()] = ch.get_properties()
        return resp


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid):
        self.path = BASE + "/service%d" % index
        self.uuid = uuid
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {GATT_SERVICE: {"UUID": self.uuid, "Primary": True,
                               "Characteristics": dbus.Array([c.get_path() for c in self.characteristics],
                                                             signature="o")}}

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.get_properties()[GATT_SERVICE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + "/char%d" % index
        self.uuid = uuid
        self.flags = flags
        self.service = service
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {GATT_CHRC: {"Service": self.service.get_path(), "UUID": self.uuid,
                            "Flags": dbus.Array(self.flags, signature="s")}}

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.get_properties()[GATT_CHRC]


class Protocol:
    """Estado partilhado entre RX e STATUS."""
    def __init__(self):
        self.status = b"READY"
        self.buffer = bytearray()
        self.receiving = False
        self.last_activity = 0.0

    def process(self, raw):
        try:
            cmd = json.loads(raw.decode())
            if not isinstance(cmd, dict):
                raise ValueError("JSON tem de ser um objeto")
            log("comando:", cmd.get("cmd"), cmd.get("ssid", ""))
            resp = handle(cmd)
        except Exception as e:
            resp = {"ok": False, "error": str(e)}
        self.status = json.dumps(resp, ensure_ascii=False).encode()[:1024]
        return False


class RxChrc(Characteristic):
    def __init__(self, bus, index, service, proto):
        Characteristic.__init__(self, bus, index, RX_UUID, ["write", "write-without-response"], service)
        self.proto = proto

    @dbus.service.method(GATT_CHRC, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        p = self.proto
        p.last_activity = time.time()
        pkt = bytes(value)
        if pkt == b"B":
            p.buffer = bytearray()
            p.receiving = True
            p.status = b"BUSY"
        elif pkt[:1] == b"D" and p.receiving:
            if len(p.buffer) + len(pkt) - 1 > 512:
                p.receiving = False
                p.status = b'{"ok":false,"error":"comando demasiado longo"}'
            else:
                p.buffer.extend(pkt[1:])
        elif pkt == b"E" and p.receiving:
            p.receiving = False
            GLib.idle_add(p.process, bytes(p.buffer))
        else:
            p.status = b'{"ok":false,"error":"protocolo"}'


class StatusChrc(Characteristic):
    def __init__(self, bus, index, service, proto):
        Characteristic.__init__(self, bus, index, STATUS_UUID, ["read"], service)
        self.proto = proto

    @dbus.service.method(GATT_CHRC, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        self.proto.last_activity = time.time()
        off = int(options.get("offset", 0))
        return dbus.ByteArray(self.proto.status[off:])


class Advertisement(dbus.service.Object):
    def __init__(self, bus):
        self.path = BASE + "/adv0"
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return {"Type": "peripheral", "LocalName": dbus.String(NAME)}

    @dbus.service.method(LE_ADV, in_signature="", out_signature="")
    def Release(self):
        log("anuncio libertado pelo BlueZ")


# ---------------------------------------------------------------------------
# Janela BLE
# ---------------------------------------------------------------------------
class Controller:
    def __init__(self, bus):
        self.bus = bus
        self.adapter = self._find_adapter()
        props = dbus.Interface(bus.get_object(BLUEZ, self.adapter), DBUS_PROP)
        props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))
        self.gatt = dbus.Interface(bus.get_object(BLUEZ, self.adapter), GATT_MANAGER)
        self.advm = dbus.Interface(bus.get_object(BLUEZ, self.adapter), ADV_MANAGER)
        self.proto = Protocol()
        self.app = Application(bus)
        svc = Service(bus, 0, SERVICE_UUID)
        svc.characteristics = [RxChrc(bus, 0, svc, self.proto), StatusChrc(bus, 1, svc, self.proto)]
        self.app.services.append(svc)
        self.adv = Advertisement(bus)
        self.active = False
        self.boot_deadline = time.time() + BOOT_WINDOW_S

    def _find_adapter(self):
        om = dbus.Interface(self.bus.get_object(BLUEZ, "/"), DBUS_OM)
        for path, ifaces in om.GetManagedObjects().items():
            if GATT_MANAGER in ifaces and ADV_MANAGER in ifaces:
                return path
        raise RuntimeError("Adaptador Bluetooth com GATT/LE advertising nao encontrado")

    # As chamadas ao BlueZ sao assincronas: ao registar, o BlueZ chama de volta
    # GetManagedObjects/GetAll neste processo, o que bloquearia uma chamada sincrona.
    def _err(self, what):
        def handler(e):
            log("erro em %s: %s" % (what, e.get_dbus_message() if hasattr(e, "get_dbus_message") else e))
            if what.startswith("Register"):
                self.active = False
        return handler

    def _set_adv_interval(self):
        lo, hi = ADV_INTERVAL
        try:
            # min primeiro (o kernel exige min <= max em cada escrita)
            for name, val in (("adv_min_interval", lo), ("adv_max_interval", hi)):
                with open(DEBUGFS + name, "w") as f:
                    f.write(str(val))
        except OSError as e:
            log("aviso: nao foi possivel mudar o intervalo de anuncio:", e)

    def open(self, reason):
        if self.active:
            return
        self.active = True
        self._set_adv_interval()
        self.proto.status = b"READY"
        self.gatt.RegisterApplication(self.app.path, {}, reply_handler=lambda: log("servico GATT registado"),
                                      error_handler=self._err("RegisterApplication"))
        self.advm.RegisterAdvertisement(self.adv.get_path(), {},
                                        reply_handler=lambda: log("a anunciar como '%s' (%s)" % (NAME, reason)),
                                        error_handler=self._err("RegisterAdvertisement"))

    def close(self, reason, sync=False):
        if not self.active:
            return
        self.active = False
        for fn, arg in ((self.advm.UnregisterAdvertisement, self.adv.get_path()),
                        (self.gatt.UnregisterApplication, self.app.path)):
            try:
                if sync:
                    fn(arg)
                else:
                    fn(arg, reply_handler=lambda: None, error_handler=self._err("Unregister"))
            except dbus.exceptions.DBusException as e:
                log("aviso ao fechar:", e.get_dbus_message())
        log("desativado (%s)" % reason)

    def tick(self):
        try:
            in_boot = time.time() < self.boot_deadline
            online = wifi_connected()
            busy = time.time() - self.proto.last_activity < 60
            if in_boot or not online:
                self.open("arranque" if in_boot else "sem Wi-Fi")
            elif not busy:
                self.close("Wi-Fi ligado e janela de arranque terminada")
        except Exception as e:
            log("erro:", e)
        return True


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    ctl = Controller(bus)
    ctl.tick()
    GLib.timeout_add_seconds(CHECK_S, ctl.tick)
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        ctl.close("paragem", sync=True)


if __name__ == "__main__":
    sys.exit(main())
