#!/bin/sh
# Instala a consola ColdRoom neste Raspberry Pi (correr na pasta onde estao os ficheiros).
#   sh install.sh
set -e
cd "$(dirname "$0")"
DEST=/opt/coldroom-console
RUN_USER=$(id -un)

echo "== 1/4 dependencias (paho-mqtt, dbus, gi)"
python3 -c "import paho.mqtt" 2>/dev/null || { sudo apt-get update -qq && sudo apt-get install -y python3-paho-mqtt; }
python3 -c "import dbus, gi" 2>/dev/null || sudo apt-get install -y python3-dbus python3-gi

echo "== 2/4 copiar ficheiros para $DEST (utilizador: $RUN_USER)"
sudo mkdir -p "$DEST/static"
# Mantem o config.py que ja la estiver (para nao perder alteracoes feitas no Pi)
[ -f "$DEST/config.py" ] || sudo cp config.py "$DEST/"
sudo cp coldroom_console.py coldroom_examples.py demo_sim.py coldroom_ble.py "$DEST/"
sudo cp static/index.html "$DEST/static/"
sudo chown -R "$RUN_USER":"$RUN_USER" "$DEST"

echo "== 3/4 servicos systemd (consola + camaras de exemplo)"
for svc in coldroom-console coldroom-examples; do
  sed "s/^User=.*/User=$RUN_USER/" $svc.service | sudo tee /etc/systemd/system/$svc.service >/dev/null
done
sudo cp coldroom-ble.service /etc/systemd/system/   # corre como root (BlueZ + wpa_cli)
sudo cp coldroom-wifi-prefer.service coldroom-wifi-prefer.timer /etc/systemd/system/   # voltar a rede preferida
sudo systemctl daemon-reload
sudo systemctl enable --now coldroom-wifi-prefer.timer >/dev/null 2>&1
for svc in coldroom-console coldroom-examples coldroom-ble; do
  sudo systemctl enable $svc >/dev/null 2>&1
  sudo systemctl restart $svc
done

echo "== 4/4 verificar"
sleep 4
for svc in coldroom-console coldroom-examples coldroom-ble; do
  echo "$svc: $(systemctl is-active $svc)"
  journalctl -u $svc -n 6 --no-pager -o cat
done
PORT=$(python3 -c "import sys; sys.path.insert(0,'$DEST'); import config; print(getattr(config,'HTTP_PORT',8080))")
echo "Consola: http://$(hostname -I | awk '{print $1}'):$PORT/"
