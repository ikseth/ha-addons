#!/usr/bin/with-contenv bashio
set -e

OPTIONS_FILE="/data/options.json"
export HA4LINUX_CONFIG_FILE="${OPTIONS_FILE}"

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
export HA4LINUX_SENSORS_FILESYSTEM="true"
export HA4LINUX_SENSORS_SYSTEM_INFO="true"
export HA4LINUX_SENSORS_APP_POLICIES="true"
export HA4LINUX_SYSTEM_UPDATES_ENABLED="true"
export HA4LINUX_SYSTEM_UPDATES_CHECK_INTERVAL_SEC="86400"
export HA4LINUX_SYSTEM_UPDATES_COMMAND_TIMEOUT_SEC="60"
export HA4LINUX_SYSTEM_UPDATES_MAX_PACKAGES="25"
export HA4LINUX_READONLY_MODE="false"
export HA4LINUX_ACTUATOR_SESSION="true"
export HA4LINUX_ACTUATOR_APP_POLICY="true"
export HA4LINUX_ACTUATOR_VIRTUALBOX="false"
export HA4LINUX_ACTUATOR_MESSAGE="true"
export HA4LINUX_ALLOWED_SESSION_USERS=""
export HA4LINUX_MESSAGE_ALLOWED_TARGETS="broadcast"
export HA4LINUX_VIRTUALBOX_USER=""
export HA4LINUX_VIRTUALBOX_ALLOWED_ACTIONS="start,acpi_shutdown,savestate"
export HA4LINUX_VIRTUALBOX_ALLOWED_VMS=""
export HA4LINUX_VIRTUALBOX_START_TYPE="headless"
export HA4LINUX_VIRTUALBOX_SWITCH_TURN_OFF_ACTION="acpi_shutdown"
export HA4LINUX_SERVICES_WATCHLIST=""
export HA4LINUX_FILESYSTEM_EXCLUDE_TYPES="tmpfs,ramfs,devtmpfs,proc,sysfs,cgroup,cgroup2,pstore,debugfs,tracefs,securityfs,configfs,fusectl,mqueue,hugetlbfs,autofs,bpf,binfmt_misc,squashfs,overlay,nfs,nfs4,cifs,smbfs,sshfs,fuse.sshfs,glusterfs,ceph,9p"
export HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS="/proc,/sys,/dev,/run,/var/lib/docker,/var/lib/containers"
export HA4LINUX_APP_POLICY_FILE="/data/app_policies.json"
export HA4LINUX_APP_POLICY_USE_SUDO_KILL="true"
export HA4LINUX_REMOTE_UPDATE_ENABLED="false"
export HA4LINUX_REMOTE_UPDATE_MANIFEST_URL=""
export HA4LINUX_REMOTE_UPDATE_CHANNEL="stable"
export HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC="1800"
export HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC="10"
export HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC="300"
export HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND=""
export HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND=""
export HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY="false"

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
  export HA4LINUX_SENSORS_FILESYSTEM="$(bashio::config 'sensors_filesystem')"
  export HA4LINUX_SENSORS_SYSTEM_INFO="$(bashio::config 'sensors_system_info')"
  export HA4LINUX_SENSORS_APP_POLICIES="$(bashio::config 'sensors_app_policies')"
  export HA4LINUX_SYSTEM_UPDATES_ENABLED="$(bashio::config 'system_updates_enabled')"
  export HA4LINUX_SYSTEM_UPDATES_CHECK_INTERVAL_SEC="$(bashio::config 'system_updates_check_interval_sec')"
  export HA4LINUX_SYSTEM_UPDATES_COMMAND_TIMEOUT_SEC="$(bashio::config 'system_updates_command_timeout_sec')"
  export HA4LINUX_SYSTEM_UPDATES_MAX_PACKAGES="$(bashio::config 'system_updates_max_packages')"
  export HA4LINUX_READONLY_MODE="$(bashio::config 'readonly_mode')"
  export HA4LINUX_ACTUATOR_SESSION="$(bashio::config 'actuator_session')"
  export HA4LINUX_ACTUATOR_APP_POLICY="$(bashio::config 'actuator_app_policy')"
  export HA4LINUX_ACTUATOR_VIRTUALBOX="$(bashio::config 'actuator_virtualbox')"
  export HA4LINUX_ACTUATOR_MESSAGE="$(bashio::config 'actuator_message')"
  export HA4LINUX_ALLOWED_SESSION_USERS="$(bashio::config 'allowed_session_users')"
  export HA4LINUX_MESSAGE_ALLOWED_TARGETS="$(bashio::config 'message_allowed_targets')"
  export HA4LINUX_VIRTUALBOX_USER="$(bashio::config 'virtualbox_user')"
  export HA4LINUX_VIRTUALBOX_ALLOWED_ACTIONS="$(bashio::config 'virtualbox_allowed_actions')"
  export HA4LINUX_VIRTUALBOX_ALLOWED_VMS="$(bashio::config 'virtualbox_allowed_vms')"
  export HA4LINUX_VIRTUALBOX_START_TYPE="$(bashio::config 'virtualbox_start_type')"
  export HA4LINUX_VIRTUALBOX_SWITCH_TURN_OFF_ACTION="$(bashio::config 'virtualbox_switch_turn_off_action')"
  export HA4LINUX_SERVICES_WATCHLIST="$(bashio::config 'services_watchlist')"
  export HA4LINUX_FILESYSTEM_EXCLUDE_TYPES="$(bashio::config 'filesystem_exclude_types')"
  export HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS="$(bashio::config 'filesystem_exclude_mounts')"
  export HA4LINUX_APP_POLICY_FILE="$(bashio::config 'app_policy_file')"
  export HA4LINUX_APP_POLICY_USE_SUDO_KILL="$(bashio::config 'app_policy_use_sudo_kill')"
  export HA4LINUX_REMOTE_UPDATE_ENABLED="$(bashio::config 'remote_update_enabled')"
  export HA4LINUX_REMOTE_UPDATE_MANIFEST_URL="$(bashio::config 'remote_update_manifest_url')"
  export HA4LINUX_REMOTE_UPDATE_CHANNEL="$(bashio::config 'remote_update_channel')"
  export HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC="$(bashio::config 'remote_update_check_interval_sec')"
  export HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC="$(bashio::config 'remote_update_check_timeout_sec')"
  export HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC="$(bashio::config 'remote_update_command_timeout_sec')"
  export HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND="$(bashio::config 'remote_update_apply_command')"
  export HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND="$(bashio::config 'remote_update_rollback_command')"
  export HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY="$(bashio::config 'remote_update_allow_in_readonly')"
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
