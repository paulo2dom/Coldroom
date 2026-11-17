"""Vitrine SIM - configuracao de redes Wi-Fi por Bluetooth LE (ESP32-S3 e Raspberry Pi).
Mesmo protocolo do projeto ColdRoom (Pico W).

Requer Python no Windows/Linux/macOS com Bluetooth LE e a biblioteca bleak:
    py -m pip install bleak

Exemplos:
    py desktop/vitrine_ble.py scan
    py desktop/vitrine_ble.py vitrine status
    py desktop/vitrine_ble.py vitrine add --ssid "RedeLab" --mqtt-host 192.168.1.50   (pede a password)
    py desktop/vitrine_ble.py vitrine list
    py desktop/vitrine_ble.py vitrine apply                        (reinicia o ESP32)
    py desktop/vitrine_ble.py pi status                            (Raspberry Pi / broker)

O BLE so esta ativo em janelas curtas:
  ESP32: 3 min apos arrancar, sem Wi-Fi conhecido, ou botao BOOT premido 1 s (LED azul)
  Pi:  10 min apos arrancar e sempre que nao tem Wi-Fi

AVISO (laboratorio): a ligacao BLE nao e cifrada; a password Wi-Fi passa em claro.
"""
import argparse
import asyncio
import getpass
import json
import sys

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("Falta a biblioteca bleak:  py -m pip install bleak")

RX_UUID = "7C0D1A50-2B6E-4C1F-9E31-C01D500A0002"
STATUS_UUID = "7C0D1A50-2B6E-4C1F-9E31-C01D500A0003"
PREFIXES = ("Vitrine-", "ColdRoom-")
VITRINE_PREFIX = "Vitrine-"
PI_NAME = "ColdRoom-Pi"


def _name(d, adv):
    return (adv.local_name if adv else None) or d.name or ""


async def scan(seconds=8):
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    return [(d, adv) for d, adv in found.values() if _name(d, adv).startswith(PREFIXES)]


async def find(target, name, seconds):
    def match(d, adv):
        n = _name(d, adv)
        if name:
            return n == name
        if target == "pi":
            return n == PI_NAME
        return n.startswith(VITRINE_PREFIX)

    label = name or (PI_NAME if target == "pi" else VITRINE_PREFIX + "<equipamento> (ESP32)")
    print("A procurar %s durante %d s..." % (label, seconds))
    d = await BleakScanner.find_device_by_filter(match, timeout=seconds)
    if not d:
        hint = ("botao BOOT do ESP32 premido 1 s (LED azul acende) ou reinicia-o" if target == "vitrine"
                else "reinicia o Pi ou o servico: sudo systemctl restart coldroom-ble")
        raise RuntimeError("Nao encontrado. Janela BLE fechada? %s." % hint)
    return d


async def send(client, cmd, wait_s=25):
    data = json.dumps(cmd, ensure_ascii=False).encode()
    await client.write_gatt_char(RX_UUID, b"B", response=True)
    for i in range(0, len(data), 19):
        await client.write_gatt_char(RX_UUID, b"D" + data[i:i + 19], response=True)
    await client.write_gatt_char(RX_UUID, b"E", response=True)
    for _ in range(wait_s * 4):
        await asyncio.sleep(0.25)
        raw = bytes(await client.read_gatt_char(STATUS_UUID)).decode("utf-8", "replace")
        if raw.startswith("{"):
            return json.loads(raw)
    raise TimeoutError("Sem resposta do equipamento")


def show(resp):
    if not resp.get("ok"):
        print("ERRO:", resp.get("error"))
        return 1
    if "networks" in resp and isinstance(resp["networks"], list):
        print("Redes conhecidas:")
        for n in resp["networks"]:
            extra = []
            if n.get("mqtt_host"):
                extra.append("broker " + n["mqtt_host"])
            if n.get("priority") is not None:
                extra.append("prioridade %s" % n["priority"])
            if n.get("current"):
                extra.append("LIGADA")
            if n.get("source"):
                extra.append("origem: " + n["source"])
            print("  - %-28s %s" % (n.get("ssid"), " | ".join(extra)))
        return 0
    for k, v in resp.items():
        if k != "ok":
            print("  %-15s %s" % (k, v))
    return 0


async def run(args):
    if args.target == "scan":
        found = await scan(args.scan)
        if not found:
            print("Nenhum equipamento Vitrine/ColdRoom com BLE ativo.")
        for d, adv in found:
            print("  %-22s %s  (%s dBm)" % (_name(d, adv), d.address, getattr(adv, "rssi", "?")))
        return 0

    cmd = {"cmd": args.action}
    if args.action in ("add", "remove"):
        if not args.ssid:
            raise SystemExit("Indica --ssid")
        cmd["ssid"] = args.ssid
    if args.action == "add":
        pw = args.password if args.password is not None else getpass.getpass(
            "Password de '%s' (Enter = rede aberta): " % args.ssid)
        cmd["password"] = pw
        if args.target == "vitrine" and args.mqtt_host:
            cmd["mqtt_host"] = args.mqtt_host
        if args.target == "pi" and args.priority is not None:
            cmd["priority"] = args.priority
        print("AVISO: BLE sem cifra (laboratorio) - a password passa em claro.")
    if args.action == "remove" and args.force:
        cmd["force"] = True

    device = await find(args.target, args.name, args.scan)
    async with BleakClient(device, timeout=20) as client:
        print("Ligado a %s (%s)" % (device.name, device.address))
        return show(await send(client, cmd))


def main():
    ap = argparse.ArgumentParser(description="Vitrine SIM - redes Wi-Fi por Bluetooth (ESP32-S3 e Raspberry Pi)")
    ap.add_argument("target", choices=["vitrine", "pi", "scan"], help="equipamento a configurar, ou scan")
    ap.add_argument("action", nargs="?", default="status",
                    choices=["status", "list", "add", "remove", "apply"],
                    help="status | list | add | remove | apply (aplica: ESP32 reinicia, Pi reconfigura o Wi-Fi)")
    ap.add_argument("--ssid")
    ap.add_argument("--password", help="(evitar: fica no historico; sem isto e pedida)")
    ap.add_argument("--mqtt-host", help="ESP32: IP do Raspberry Pi (broker) nessa rede")
    ap.add_argument("--priority", type=int, help="Pi: prioridade da rede (maior = preferida)")
    ap.add_argument("--force", action="store_true", help="Pi: permitir remover a rede em uso")
    ap.add_argument("--name", help="nome BLE exato, ex.: Vitrine-VT-02")
    ap.add_argument("--scan", type=int, default=20, help="segundos de procura BLE")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except (RuntimeError, TimeoutError, OSError) as e:
        print("Erro:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
