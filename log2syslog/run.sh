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

# (Aquí generas el syslog-ng.conf dinámico)
# ...

log "Configuración syslog-ng generada:"
cat /etc/syslog-ng/syslog-ng.conf | tee -a "$LOG_FILE"

log "Arrancando syslog-ng en foreground con debug..."

syslog-ng -Fvde 2>&1 | tee -a "$LOG_FILE"

