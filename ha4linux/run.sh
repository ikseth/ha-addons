#!/usr/bin/with-contenv bashio
set -e

OPTIONS_FILE="/data/options.json"

export HA4LINUX_BIND_HOST="0.0.0.0"
export HA4LINUX_BIND_PORT="8099"
export HA4LINUX_API_TOKEN=""
export HA4LINUX_TLS_ENABLED="true"
export HA4LINUX_TLS_CERTFILE="/ssl/fullchain.pem"
export HA4LINUX_TLS_KEYFILE="/ssl/privkey.pem"
export HA4LINUX_SENSORS_CPU="true"
export HA4LINUX_SENSORS_MEMORY="true"
export HA4LINUX_SENSORS_NETWORK="true"
export HA4LINUX_SENSORS_RAID="true"
export HA4LINUX_SENSORS_VIRTUALBOX="false"
export HA4LINUX_SENSORS_SERVICES="false"
export HA4LINUX_SENSORS_APP_POLICIES="true"
export HA4LINUX_READONLY_MODE="false"
export HA4LINUX_ACTUATOR_SESSION="true"
export HA4LINUX_ACTUATOR_APP_POLICY="true"
export HA4LINUX_ALLOWED_SESSION_USERS=""
export HA4LINUX_VIRTUALBOX_USER=""
export HA4LINUX_SERVICES_WATCHLIST=""
export HA4LINUX_APP_POLICY_FILE="/data/app_policies.json"
export HA4LINUX_APP_POLICY_USE_SUDO_KILL="true"

if bashio::fs.file_exists "${OPTIONS_FILE}"; then
  export HA4LINUX_BIND_PORT="$(bashio::config 'bind_port')"
  export HA4LINUX_API_TOKEN="$(bashio::config 'api_token')"
  export HA4LINUX_TLS_ENABLED="$(bashio::config 'tls_enabled')"
  export HA4LINUX_TLS_CERTFILE="$(bashio::config 'tls_certfile')"
  export HA4LINUX_TLS_KEYFILE="$(bashio::config 'tls_keyfile')"
  export HA4LINUX_SENSORS_CPU="$(bashio::config 'sensors_cpu')"
  export HA4LINUX_SENSORS_MEMORY="$(bashio::config 'sensors_memory')"
  export HA4LINUX_SENSORS_NETWORK="$(bashio::config 'sensors_network')"
  export HA4LINUX_SENSORS_RAID="$(bashio::config 'sensors_raid')"
  export HA4LINUX_SENSORS_VIRTUALBOX="$(bashio::config 'sensors_virtualbox')"
  export HA4LINUX_SENSORS_SERVICES="$(bashio::config 'sensors_services')"
  export HA4LINUX_SENSORS_APP_POLICIES="$(bashio::config 'sensors_app_policies')"
  export HA4LINUX_READONLY_MODE="$(bashio::config 'readonly_mode')"
  export HA4LINUX_ACTUATOR_SESSION="$(bashio::config 'actuator_session')"
  export HA4LINUX_ACTUATOR_APP_POLICY="$(bashio::config 'actuator_app_policy')"
  export HA4LINUX_ALLOWED_SESSION_USERS="$(bashio::config 'allowed_session_users')"
  export HA4LINUX_VIRTUALBOX_USER="$(bashio::config 'virtualbox_user')"
  export HA4LINUX_SERVICES_WATCHLIST="$(bashio::config 'services_watchlist')"
  export HA4LINUX_APP_POLICY_FILE="$(bashio::config 'app_policy_file')"
  export HA4LINUX_APP_POLICY_USE_SUDO_KILL="$(bashio::config 'app_policy_use_sudo_kill')"
fi

if [ -z "${HA4LINUX_API_TOKEN}" ] || [ "${HA4LINUX_API_TOKEN}" = "null" ]; then
  bashio::log.error "api_token is required"
  exit 1
fi

if [ "${HA4LINUX_TLS_ENABLED}" = "true" ] || [ "${HA4LINUX_TLS_ENABLED}" = "True" ]; then
  if [ ! -f "${HA4LINUX_TLS_CERTFILE}" ]; then
    bashio::log.error "TLS cert not found: ${HA4LINUX_TLS_CERTFILE}"
    exit 1
  fi

  if [ ! -f "${HA4LINUX_TLS_KEYFILE}" ]; then
    bashio::log.error "TLS key not found: ${HA4LINUX_TLS_KEYFILE}"
    exit 1
  fi
fi

exec python3 -m app.main
