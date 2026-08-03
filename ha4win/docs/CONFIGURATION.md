# Configuración

## Ubicación y precedencia

Fichero principal: `C:\ProgramData\HA4Win\config.json`.

Precedencia efectiva, de mayor a menor —la misma de ha4linux:

1. Variables de entorno `HA4WIN_*`
2. `config.json`
3. Valores por defecto internos

La ruta se puede sobrescribir con `HA4WIN_CONFIG_FILE` o con `--config` en los
subcomandos. El entorno existe para depuración y para escenarios de despliegue
automatizado; el modo normal de operación es el fichero.

El fichero se lee **una vez al arrancar el servicio**. Cambiarlo requiere reiniciar
el servicio (`ha4win.exe restart` o `sc.exe stop/start ha4win`). No hay recarga en
caliente en el v1; el endpoint `/v1/config/*` de configuración remota declarativa
queda como fase futura, igual que en ha4linux.

## Fichero completo con valores por defecto

```json
{
  "api": {
    "bind_host": "0.0.0.0",
    "bind_port": 8099,
    "token": "",
    "allowed_clients": [],
    "sensor_timeout_sec": 3
  },
  "tls": {
    "enabled": true,
    "certfile": "C:\\ProgramData\\HA4Win\\certs\\ha4win.crt",
    "keyfile": "C:\\ProgramData\\HA4Win\\certs\\ha4win.key",
    "self_signed": {
      "auto_generate": true,
      "valid_days": 3650,
      "subject_alt_names": []
    }
  },
  "modules": {
    "cpu": { "enabled": true, "per_core": true },
    "memory": { "enabled": true },
    "network": {
      "enabled": true,
      "include_interfaces": [],
      "exclude_interfaces": ["Loopback*", "isatap*", "Teredo*", "vEthernet*", "VirtualBox*", "VMware*"],
      "aggregate_mode": "selected"
    },
    "volumes": {
      "enabled": true,
      "include_drive_types": ["fixed"],
      "exclude_mounts": []
    },
    "services": {
      "enabled": false,
      "watchlist": []
    },
    "system_info": {
      "enabled": true,
      "updates_enabled": true,
      "updates_provider": "wua",
      "updates_search_scope": "default",
      "updates_check_interval_sec": 86400,
      "updates_timeout_sec": 600,
      "updates_max_packages": 25
    },
    "maintenance": { "enabled": true },
    "security": {
      "enabled": true,
      "defender": true,
      "firewall": true,
      "bitlocker": false,
      "refresh_interval_sec": 300
    }
  },
  "actuators": {
    "power": {
      "enabled": true,
      "allowed_actions": ["lock"],
      "default_delay_seconds": 30
    }
  },
  "management": {
    "remote_update": {
      "enabled": false,
      "manifest_url": "",
      "channel": "stable",
      "check_interval_sec": 1800,
      "check_timeout_sec": 10,
      "apply_timeout_sec": 300,
      "allow_in_readonly": false,
      "require_signed_asset": false,
      "health_check_timeout_sec": 60
    }
  },
  "readonly_mode": false,
  "logging": {
    "level": "info",
    "file_enabled": true,
    "max_size_mb": 10,
    "max_files": 5,
    "eventlog_enabled": true
  }
}
```

## Variables de entorno equivalentes

Regla de derivación: `HA4WIN_` + ruta en mayúsculas separada por `_`.

| Ruta JSON | Variable |
| --- | --- |
| `api.bind_port` | `HA4WIN_API_BIND_PORT` |
| `api.token` | `HA4WIN_API_TOKEN` |
| `tls.enabled` | `HA4WIN_TLS_ENABLED` |
| `modules.services.watchlist` | `HA4WIN_MODULES_SERVICES_WATCHLIST` (separado por comas) |
| `actuators.power.allowed_actions` | `HA4WIN_ACTUATORS_POWER_ALLOWED_ACTIONS` |
| `readonly_mode` | `HA4WIN_READONLY_MODE` |

Las listas admiten valor separado por comas. Los booleanos aceptan
`1/true/yes/on` sin distinguir mayúsculas, igual que el `_as_bool` de ha4linux.

## Validación

`ha4win.exe config validate` comprueba y devuelve código de salida distinto de cero
ante cualquier error. El servicio ejecuta exactamente la misma validación al
arrancar y **se niega a arrancar** si falla, registrando el motivo en el Event Log.

Reglas:

| Regla | Efecto |
| --- | --- |
| `api.token` vacío | Error fatal |
| `api.token` con menos de 24 caracteres | Aviso en log, arranca |
| `api.bind_port` fuera de 1–65535 | Error fatal |
| `api.allowed_clients` con CIDR inválido | Error fatal |
| `tls.enabled` con ficheros inexistentes y `auto_generate: false` | Error fatal |
| `tls.enabled` con ficheros inexistentes y `auto_generate: true` | Genera el par y continúa |
| `tls.enabled: false` con `bind_host` distinto de `127.0.0.1` | Aviso destacado en log y Event Log |
| `modules.services.enabled: true` con watchlist vacía | El módulo no se registra; aviso |
| `actuators.power.allowed_actions` con acción desconocida | Error fatal (nombre mal escrito no debe degradar en silencio) |
| `readonly_mode: true` | Ningún actuador se registra; se ignora `actuators.*` |
| `management.remote_update.enabled: true` sin `manifest_url` | Error fatal |
| Claves desconocidas en el JSON | Aviso con la ruta exacta; no fatal |

`ha4win.exe config print` imprime la configuración **efectiva** ya resuelta (con
env aplicado y defaults rellenados), con el token censurado como `***`. Es la
herramienta de diagnóstico para "¿por qué no aparece este sensor?".

## Permisos del fichero

El instalador aplica un DACL explícito sobre `C:\ProgramData\HA4Win`, rompiendo la
herencia:

| Principal | Permiso |
| --- | --- |
| `NT AUTHORITY\SYSTEM` | Control total |
| `BUILTIN\Administrators` | Control total |
| *(nadie más)* | — |

Es imprescindible: `C:\ProgramData` es legible por `Users` por defecto, y ahí viven
el token de API y la clave privada TLS. El subcomando `config validate` comprueba
el DACL y avisa si alguien ha restaurado la herencia.

## Perfiles de referencia

**Host mínimo / aislado** — sin conectividad a Internet:

```json
{
  "api": { "bind_port": 8099, "token": "…", "allowed_clients": ["198.51.100.0/24"] },
  "modules": {
    "system_info": { "updates_enabled": false },
    "security": { "defender": false, "bitlocker": false },
    "services": { "enabled": false }
  },
  "management": { "remote_update": { "enabled": false } }
}
```

Resultado: solo syscalls y registro. Sin COM, sin red saliente, sin procesos hijo.

**Estación de trabajo gestionada**:

```json
{
  "modules": {
    "services": { "enabled": true, "watchlist": ["Spooler", "WSearch", "MSSQLSERVER"] },
    "system_info": { "updates_enabled": true, "updates_search_scope": "managed" },
    "security": { "bitlocker": true }
  },
  "actuators": { "power": { "allowed_actions": ["lock", "restart", "shutdown"], "default_delay_seconds": 60 } },
  "management": {
    "remote_update": {
      "enabled": true,
      "manifest_url": "https://raw.githubusercontent.com/ikseth/ha-addons/main/ha4win/update-manifest.json"
    }
  }
}
```

**Servidor en modo observación**:

```json
{
  "readonly_mode": true,
  "modules": { "services": { "enabled": true, "watchlist": ["W3SVC", "MSSQLSERVER"] } }
}
```
