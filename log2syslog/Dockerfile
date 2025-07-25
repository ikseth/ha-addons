FROM alpine:3.18

RUN apk add --no-cache syslog-ng bash jq

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
