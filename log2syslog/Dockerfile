FROM alpine:3.20

# syslog-ng + herramientas de depuración (jq para leer options.json y netcat para pruebas si hiciera falta)
RUN apk add --no-cache syslog-ng jq busybox-extras

# Copiamos plantilla y entrypoint
COPY syslog-ng.conf.template /etc/syslog-ng/syslog-ng.conf.template
COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
