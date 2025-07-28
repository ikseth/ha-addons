#!/usr/bin/env bash
set -e

REMOTE_HOST=$(jq -r '.remote_host' /data/options.json)
REMOTE_PORT=$(jq -r '.remote_port' /data/options.json)
FACILITY=$(jq -r '.facility' /data/options.json)

# Dump info a los logs del add-on (que puedes ver en la UI)
echo "=== Parámetros de reenvío: $REMOTE_HOST $REMOTE_PORT $FACILITY ===" >&2
echo "=== Contenido de syslog-ng.conf generado ===" >&2
cat /syslog-ng.conf.template | \
  sed -e "s|{{ remote_host }}|$REMOTE_HOST|g" \
      -e "s|{{ remote_port }}|$REMOTE_PORT|g" \
      -e "s|{{ facility }}|$FACILITY|g" \
      | tee /syslog-ng.conf >&2

echo "=== Entradas recientes en el log de HA ===" >&2
tail -20 /config/home-assistant.log >&2

# Arranca syslog-ng normalmente
exec syslog-ng -F -f /syslog-ng.conf
