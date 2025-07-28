FROM alpine:3.18

RUN apk add --no-cache syslog-ng bash jq

COPY syslog-ng.conf.template /syslog-ng.conf.template

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
