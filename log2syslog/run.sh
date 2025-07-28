#!/usr/bin/with-contenv bash
set -e

# Lee las variables desde el options.json que Home Assistant monta en /data/options.json
REMOTE_HOST=$(jq -r '.remote_host' /data/options.json)
REMOTE_PORT=$(jq -r '.remote_port' /data/options.json)
FACILITY=$(jq -r '.facility' /data/options.json)

# Genera el syslog-ng.conf final a partir de la plantilla
sed \
  -e "s|{{ remote_host }}|$REMOTE_HOST|g" \
  -e "s|{{ remote_port }}|$REMOTE_PORT|g" \
  -e "s|{{ facility }}|$FACILITY|g" \
  /syslog-ng.conf.template > /syslog-ng.conf

# Arranca syslog-ng usando el nuevo fichero generado
syslog-ng -F -f /syslog-ng.conf
