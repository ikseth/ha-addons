#!/bin/sh
set -e

TEMPLATE="/etc/syslog-ng/syslog-ng.conf.template"
CONFIG="/etc/syslog-ng/syslog-ng.conf"
OPTIONS="/data/options.json"
LOCAL_LOG="/data/syslog-ng-ha.log"

# Lee opciones del usuario
DEST_IP=$(jq -r .dest_ip "$OPTIONS")
DEST_PORT=$(jq -r .dest_port "$OPTIONS")
DEBUG=$(jq -r .debug "$OPTIONS")

# Genera config desde plantilla
sed -e "s|{{DEST_IP}}|$DEST_IP|g" \
    -e "s|{{DEST_PORT}}|$DEST_PORT|g" \
    "$TEMPLATE" > "$CONFIG"

echo "[INIT] Config generado para syslog-ng:"
cat "$CONFIG"
echo "[INIT] Opciones: dest_ip=$DEST_IP dest_port=$DEST_PORT debug=$DEBUG"

# Asegura fichero local de depuración
touch "$LOCAL_LOG"

# Comprobación de sintaxis (no arranca, solo valida)
syslog-ng -s -f "$CONFIG" || { echo "[ERROR] Sintaxis inválida en syslog-ng.conf"; exit 1; }

# Si está en debug, vuelca el local en vivo al registro del add-on (sin bloquear)
if [ "$DEBUG" = "true" ]; then
  echo "[DEBUG] Activado tail de $LOCAL_LOG al log del add-on"
  ( tail -F "$LOCAL_LOG" 2>/dev/null & ) || true
  exec syslog-ng -Fvde
else
  exec syslog-ng -F
fi
