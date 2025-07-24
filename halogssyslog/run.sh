#!/bin/sh

export SYSLOG_REMOTE_HOST=${SYSLOG_REMOTE_HOST:-"192.168.50.62"}
export SYSLOG_REMOTE_PORT=${SYSLOG_REMOTE_PORT:-514}
export SYSLOG_FACILITY=${SYSLOG_FACILITY:-"local5"}

envsubst < /etc/syslog-ng/syslog-ng.conf > /etc/syslog-ng/syslog-ng.conf.tmp
mv /etc/syslog-ng/syslog-ng.conf.tmp /etc/syslog-ng/syslog-ng.conf

exec syslog-ng -F -f /etc/syslog-ng/syslog-ng.conf
