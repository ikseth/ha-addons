# Configuración

## Ubicación y precedencia

Fichero principal: `C:\ProgramData\HA4Win\config.json`.

Precedencia efectiva, de mayor a menor —la misma de ha4linux:

1. Variables de entorno `HA4WIN_*`
2. `config.json`
3. Valores por defecto internos

La ruta del fichero se resuelve con esta precedencia, de mayor a menor:

1. `--config <ruta>` (flag de subcomando)
2. `HA4WIN_CONFIG_FILE` (entorno)
3. Ruta por defecto `C:\ProgramData\HA4Win\config.json`

Cuando se instala con `--config` no estándar, esa ruta absoluta queda **registrada
en el servicio** (`ha4win.exe service --config "<ruta>"`, ver
[INSTALLER.md](INSTALLER.md#ciclo-de-vida-del-servicio-contrato-scm)), de modo que
el servicio arranca siempre leyendo el fichero correcto sin depender del entorno. El
entorno existe para depuración y despliegue automatizado; el modo normal es el
fichero.

### Mezcla de configuración

La configuración efectiva se construye así:

- **Merge recursivo por hojas.** Un objeto parcial en `config.json` (p. ej.
  `modules.network` sin `aggregate_mode`) se fusiona con los defaults hoja a hoja;
  no reemplaza el objeto entero. Las listas **sí** se reemplazan por completo (no se
  concatenan): `exclude_interfaces` en el fichero sustituye a la lista por defecto.
- **Entorno por campo.** Cada hoja escalar o de lista tiene variable equivalente con
  la regla `HA4WIN_` + ruta en mayúsculas separada por `_` (tabla más abajo). El
  entorno pisa el valor del fichero para esa hoja concreta.
- **Tipos y valores inválidos son fatales, no se sustituyen en silencio.** A
  diferencia del loader de ha4linux —que degrada valores inválidos a defaults—, aquí
  un tipo incorrecto o un enum fuera de rango **impide arrancar** con un mensaje que
  nombra la ruta exacta. El motivo: en un servicio desatendido, un default silencioso
  esconde un error de configuración hasta que alguien nota que el sensor no está.

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

## Certificado TLS

Perfil X.509 **normativo** del certificado autofirmado que genera `install` /
`cert generate`:

| Campo | Valor |
| --- | --- |
| Clave | ECDSA P-256 |
| Firma | ECDSA con SHA-256 |
| Subject / Issuer CN | hostname del equipo |
| SAN DNS | hostname y FQDN (si el equipo está en dominio) |
| SAN IP | todas las IPv4 e IPv6 no loopback de los adaptadores activos, más `127.0.0.1` y `::1` |
| KeyUsage | `digitalSignature`, `keyEncipherment` |
| ExtKeyUsage | `serverAuth` |
| BasicConstraints | `CA:false` |
| Validez | 10 años (`tls.self_signed.valid_days`) |
| Formato | PEM (cert y clave en ficheros separados) |
| Permisos de la clave | hereda el DACL de `C:\ProgramData\HA4Win` (solo SYSTEM y Administrators) |

Reglas de generación y mantenimiento:

- **Solo `install` y `cert generate` generan certificados.** El servicio **no**
  genera nada al arrancar: si `tls.enabled: true` y faltan los ficheros, arranca
  solo si `tls.self_signed.auto_generate: true` invocando la misma rutina que
  `cert generate`; si `auto_generate: false`, **falla al arrancar** con código de
  salida `2`. Esto evita que un servicio corriendo como LocalSystem regenere
  material criptográfico de forma inadvertida.
- **Caducidad o cambio de host/IP**: no hay renovación automática. `cert show`
  reporta la huella y la fecha de caducidad; `cert generate --force` regenera el par
  (por ejemplo tras cambiar de hostname o IP) y obliga a re-verificar la huella en
  Home Assistant si se usa pinning.
- La huella SHA-256 se imprime en la instalación y se consulta con `cert show` para
  verificación fuera de banda.

## Perfiles de referencia

**Host mínimo / aislado** — sin conectividad a Internet:

```json
{
  "api": { "bind_port": 8099, "token": "…", "allowed_clients": ["192.168.50.0/24"] },
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
