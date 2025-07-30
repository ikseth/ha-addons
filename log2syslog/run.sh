#!/bin/sh

LOG_FILE="/data/addon-debug.log"

log() {
    echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

log "===== Add-on INIT ====="

if [ ! -f /config/home-assistant.log ]; then
    log "ERROR: /config/home-assistant.log NO EXISTE."
    exit 1
else
    log "/config/home-assistant.log existe. Iniciando seguimiento..."
fi

# Mostrar tamaño/inodo actual
ls -li /config/home-assistant.log | tee -a "$LOG_FILE"

# Mostrar últimas líneas del log de HA
tail -n 10 /config/home-assistant.log | tee -a "$LOG_FILE"

log "Generando configuración dinámica de syslog-ng..."

# Variables de configuración (pueden venir de options.json, ENV, etc)
DEST_IP="${DEST_IP:-192.168.50.62}"
DEST_PORT="${DEST_PORT:-514}"
FACILITY="${FACILITY:-local5}"

cat > /etc/syslog-ng/syslog-ng.conf <<EOF
@version: 4.1

source s_ha_log {
  file("/config/home-assistant.log"
    follow-freq(1)
    flags(no-parse, follow-filename, keep-alive)
    program-override("homeassistant")
  );
};

destination d_remote_udp {
  udp("${DEST_IP}" port(${DEST_PORT})
      localport(0)
      so-keepalive(yes)
      log-fifo-size(1000)
      flush-lines(1)
  );
};

filter f_facility {
    facility(${FACILITY});
};

log {
  source(s_ha_log);
  # filter(f_facility);
  destination(d_remote_udp);
};
EOF

log "Configuración syslog-ng generada:"
cat /etc/syslog-ng/syslog-ng.conf | tee -a "$LOG_FILE"

log "Arrancando syslog-ng en foreground con debug..."

syslog-ng -Fvde 2>&1 | tee -a "$LOG_FILE"

