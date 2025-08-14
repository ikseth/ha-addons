#!/bin/sh
set -e

TEMPLATE="/etc/syslog-ng/syslog-ng.conf.template"
CONFIG="/etc/syslog-ng/syslog-ng.conf"
OPTIONS="/data/options.json"
LOCAL_LOG="/data/syslog-ng-ha.log"
INTERNAL_LOG="/data/syslog-ng-internal.log"
LOOPBACK_CAPTURE="/data/udp-loopback.log"

DEST_IP=$(jq -r .dest_ip "$OPTIONS")
DEST_PORT=$(jq -r .dest_port "$OPTIONS")
DEBUG=$(jq -r .debug "$OPTIONS")

# Genera config desde plantilla
sed -e "s|{{DEST_IP}}|$DEST_IP|g" \
    -e "s|{{DEST_PORT}}|$DEST_PORT|g" \
    "$TEMPLATE" > "$CONFIG"

echo "[INIT] Config generado:"
cat "$CONFIG"
echo "[INIT] Opciones: dest_ip=$DEST_IP dest_port=$DEST_PORT debug=$DEBUG"

# Archivos visibles para depuración
touch "$LOCAL_LOG" "$INTERNAL_LOG" "$LOOPBACK_CAPTURE"

# === Diagnóstico de red previo (sin necesidad de docker exec) ===
echo "[NET] Rutas del contenedor:"
ip route || true

echo "[NET] Prueba de reachability (ping -c1 -W1) a $DEST_IP:"
ping -c1 -W1 "$DEST_IP" >/dev/null 2>&1 && echo "[NET] ping OK" || echo "[NET] ping FALLÓ (puede estar bloqueado ICMP y no significa nada para UDP)"

echo "[NET] Probing UDP con netcat (modo scan) hacia $DEST_IP:$DEST_PORT:"
# Busybox nc soporta -z -u -v en alpine/busybox-extras
nc -zvu "$DEST_IP" "$DEST_PORT" >/data/nc-probe.log 2>&1 && PROBE="OK" || PROBE="FALLO"
echo "[NET] nc -zvu resultado: $PROBE (ver /data/nc-probe.log)"

# === Listener UDP local para capturar lo que syslog-ng envía al loopback ===
# Nota: esto NO bloquea el script; se deja en background
echo "[LOOPBACK] Levantando listener UDP local 127.0.0.1:5514 --> $LOOPBACK_CAPTURE"
( nc -ul -p 5514 >> "$LOOPBACK_CAPTURE" 2>&1 & ) || true

# === Verificación de sintaxis antes de arrancar ===
if ! syslog-ng -s -f "$CONFIG"; then
  echo "[ERROR] Sintaxis inválida en $CONFIG"; exit 1;
fi

# === Arranque syslog-ng ===
if [ "$DEBUG" = "true" ]; then
  echo "[DEBUG] Tail en vivo de $LOCAL_LOG y $INTERNAL_LOG"
  ( tail -F "$LOCAL_LOG" 2>/dev/null & ) || true
  ( tail -F "$INTERNAL_LOG" 2>/dev/null & ) || true
  echo "[DEBUG] Tail en vivo de loopback UDP capturado en $LOOPBACK_CAPTURE"
  ( tail -F "$LOOPBACK_CAPTURE" 2>/dev/null & ) || true
  exec syslog-ng -Fvde -f "$CONFIG"
else
  exec syslog-ng -F -f "$CONFIG"
fi
