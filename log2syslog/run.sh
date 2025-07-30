#!/bin/sh

set -e

# Rutas
TEMPLATE="/etc/syslog-ng/syslog-ng.conf.template"
CONFIG="/etc/syslog-ng/syslog-ng.conf"
OPTIONS="/data/options.json"

# Leer opciones desde options.json (usa jq)
DEST_IP=$(jq -r .dest_ip "$OPTIONS")
DEST_PORT=$(jq -r .dest_port "$OPTIONS")
FACILITY=$(jq -r .facility "$OPTIONS")

# Sustituye las variables en la plantilla
cat "$TEMPLATE" | \
  sed "s|{{DEST_IP}}|$DEST_IP|g" | \
  sed "s|{{DEST_PORT}}|$DEST_PORT|g" | \
  sed "s|{{FACILITY}}|$FACILITY|g" \
  > "$CONFIG"

echo "==== syslog-ng.conf generado ===="
cat "$CONFIG"

echo "==== Arrancando syslog-ng ===="
exec syslog-ng -Fvde
