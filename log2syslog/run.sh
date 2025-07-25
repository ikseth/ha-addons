#!/bin/sh

# Carga opciones desde options.json (pasado por HA como /data/options.json)
REMOTE_HOST=$(jq -r '.remote_host' /data/options.json)
REMOTE_PORT=$(jq -r '.remote_port' /data/options.json)
FACILITY=$(jq -r '.facility' /data/options.json)

# Genera el syslog-ng.conf dinámicamente
cat > /etc/syslog-ng/syslog-ng.conf <<EOF
@version: 3.38
source s_ha_log {
  file("/config/home-assistant.log" follow_freq(1) flags(no-parse));
};
destination d_remote_syslog {
  syslog("${REMOTE_HOST}" port(${REMOTE_PORT}) facility(${FACILITY}));
};
log {
  source(s_ha_log);
  destination(d_remote_syslog);
};
EOF

# Arranca syslog-ng en foreground
exec syslog-ng -Fv
