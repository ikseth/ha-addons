FROM ghcr.io/hassio-addons/base:14.2.3

RUN apk add --no-cache syslog-ng

COPY syslog-ng.conf /etc/syslog-ng/syslog-ng.conf
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
