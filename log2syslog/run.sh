#!/usr/bin/env bash
set -e

REMOTE_HOST=$(jq -r '.remote_host' /data/options.json)
REMOTE_PORT=$(jq -r '.remote_port' /data/options.json)
FACILITY=$(jq -r '.facility' /data/options.json)

sed \
  -e "s|{{ remote_host }}|$REMOTE_HOST|g" \
  -e "s|{{ remote_port }}|$REMOTE_PORT|g" \
  -e "s|{{ facility }}|$FACILITY|g" \
  /syslog-ng.conf.template > /syslog-ng.conf

exec syslog-ng -F -f /syslog-ng.conf
