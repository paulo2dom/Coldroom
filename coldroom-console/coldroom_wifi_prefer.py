#!/usr/bin/env python3
"""ColdRoom: volta à rede Wi-Fi preferida quando ela está disponível.

O wpa_supplicant liga-se sozinho à rede de reserva (my_home) quando a preferida
(NOS) cai, mas não volta à preferida quando ela regressa. Este script (corrido de
2 em 2 min pelo coldroom-wifi-prefer.timer) faz essa volta, para o Pi ficar sempre
na mesma rede que o Pico e o ESP32 (que seguem as mesmas prioridades).
"""
import re
import subprocess
import sys
import time

IFACE = "wlan0"
CONF = "/etc/wpa_supplicant/wpa_supplicant.conf"
MIN_SIGNAL = -80


def wpa(*args):
    return subprocess.run(["wpa_cli", "-i", IFACE] + list(args), capture_output=True,
                          text=True, timeout=15).stdout


def main():
    nets = []
    for block in re.findall(r"network=\{(.*?)\n\}", open(CONF).read(), re.S):
        ssid = re.search(r'\bssid="([^"]*)"', block)
        prio = re.search(r"\bpriority=(\d+)", block)
        if ssid:
            nets.append((int(prio.group(1)) if prio else 0, ssid.group(1)))
    if not nets:
        return 0
    best_prio = max(p for p, _ in nets)
    preferred = [s for p, s in nets if p == best_prio]
    status = dict(l.split("=", 1) for l in wpa("status").splitlines() if "=" in l)
    current = status.get("ssid")
    if current in preferred or status.get("wpa_state") != "COMPLETED":
        return 0   # já na preferida, ou o wpa_supplicant ainda está a ligar sozinho
    wpa("scan")
    time.sleep(5)
    seen = {}
    for line in wpa("scan_results").splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 5:
            seen[f[4]] = max(seen.get(f[4], -999), int(f[2]))
    target = next((s for s in preferred if seen.get(s, -999) > MIN_SIGNAL), None)
    if not target:
        return 0
    ids = {}
    for line in wpa("list_networks").splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 2:
            ids[f[1]] = f[0]
    if target not in ids:
        return 0
    print("Rede preferida %s disponível (%d dBm); a sair de %s" % (target, seen[target], current))
    wpa("select_network", ids[target])
    time.sleep(10)
    wpa("enable_network", "all")    # manter a reserva ativa para a próxima queda
    return 0


if __name__ == "__main__":
    sys.exit(main())
