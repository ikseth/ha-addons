# Contrato API v1

**Extensión compatible de la familia v1 de ha4linux.** No es idéntico byte a byte:
comparte la forma de transporte, la autenticación Bearer, el envoltorio de
`/v1/sensors`, el patrón de `/v1/update/*` y la evaluación de compatibilidad, pero
añade el campo `platform`, sensores nuevos (`volumes`, `maintenance`, `security`),
campos descriptivos en `network`, un actuador distinto (`power_manager`) y nombres
de módulo propios de Windows. Por eso declara `schema_version = 1.1`. El subconjunto
común con ha4linux es el que permite reutilizar `api.py`/`coordinator.py`; lo que
va más allá pertenece al esquema 1.1. Las diferencias están marcadas
explícitamente en cada sección.

## Transporte y autenticación

- HTTPS por defecto (`tls.enabled = true`), certificado autofirmado generado en la
  instalación. HTTP plano solo si se desactiva TLS de forma explícita.
- `Authorization: Bearer <token>` en todos los endpoints salvo `GET /health`.
- La comparación del token se hace en **tiempo constante** (`crypto/subtle`).
  Es una divergencia deliberada respecto de ha4linux, que usa `!=`.
- Un token vacío en configuración impide arrancar el servicio.

### Control de acceso por origen (`allowed_clients`)

- Si `api.allowed_clients` no está vacío, la IP de origen debe pertenecer a alguno
  de los CIDR listados; en caso contrario se responde `403`.
- **La allowlist se evalúa antes que el token**: un origen no permitido recibe `403`
  sin que su cabecera `Authorization` llegue a compararse.
- **La IP de origen es la del peer TCP de la conexión.** No se leen cabeceras
  `X-Forwarded-For` ni `Forwarded`: el agente está pensado para acceso directo desde
  Home Assistant, no detrás de un proxy inverso.
- **IPv4 e IPv6 desde el primer día.** Las direcciones IPv4-mapped IPv6
  (`::ffff:192.168.0.10`) se normalizan a su forma IPv4 antes de comparar; los
  identificadores de zona (`fe80::1%eth0`) se descartan antes de la comparación.
  Ambas familias se soportan en la Fase 0, no se aplazan.

## Endpoints

| Método | Ruta | Auth | Descripción |
| --- | --- | --- | --- |
| GET | `/health` | no | Vivacidad. Usado por el rollback del updater |
| GET | `/v1/version` | sí | Versión, esquema, rango de compatibilidad, plataforma |
| GET | `/v1/capabilities` | sí | Módulos activos y acciones disponibles |
| GET | `/v1/sensors` | sí | Telemetría de todos los sensores registrados |
| GET | `/v1/update/status` | sí | Estado de la actualización remota |
| POST | `/v1/update/check` | sí | Fuerza la comprobación del manifiesto |
| POST | `/v1/update/apply` | sí | Aplica la actualización |
| POST | `/v1/update/rollback` | sí | Vuelve a la versión anterior |
| POST | `/v1/actuators/{actuator_id}/{action}` | sí | Ejecuta una acción |

No se implementan `/v1/tray/*` en el v1: no hay agente de bandeja.

## Forma canónica de respuesta

Las acciones y operaciones de gestión devuelven siempre un objeto con `ok`:

```json
{ "ok": false, "error": "Action 'shutdown' not allowed" }
```

Un actuador inexistente o deshabilitado devuelve `200` con
`{"ok": false, "error": "Actuator 'x' not available or disabled"}` — igual que
ha4linux, para que la integración distinga "no soportado" de "fallo de transporte".

**Todas las respuestas de error usan el mismo objeto** `{"ok": false, "error": "…"}`,
incluidas las generadas por el middleware (auth, allowlist, tamaño, ruta), no solo
las de los handlers de negocio. Todas se sirven con `Content-Type: application/json`.

Códigos HTTP:

| Código | Causa |
| --- | --- |
| `400` | Cuerpo JSON malformado o `Content-Type` inesperado en un POST con cuerpo |
| `401` | Token ausente o inválido |
| `403` | Origen fuera de `allowed_clients` |
| `404` | Ruta desconocida |
| `405` | Método no permitido en una ruta conocida |
| `413` | Cuerpo mayor de 64 KiB |
| `503` | Servidor saturado: no hubo plaza de concurrencia en el plazo corto (ver *Límites operativos*) |
| `500` | Solo ante fallo no controlado |

## GET /health

```json
{ "status": "ok" }
```

## GET /v1/version

```json
{
  "api_version": "0.1.0",
  "schema_version": "1.1",
  "platform": "windows",
  "min_integration_version": "0.1.0",
  "max_integration_version": "0.9.x",
  "build": {
    "commit": "a1b2c3d",
    "date": "2026-08-03T10:00:00Z",
    "channel": "stable",
    "go_version": "go1.23.5",
    "arch": "amd64"
  }
}
```

`platform` es la adición al esquema respecto de ha4linux por la que
`schema_version` es `1.1`. Un cliente de esquema 1.0 que ignore el campo sigue
funcionando. Cuando ha4linux añada `platform: "linux"`, debe declarar también `1.1`.

**Valores de `build`.** `commit`, `date` y `channel` se inyectan por `ldflags` en
las releases. En un binario compilado sin inyección (build local de desarrollo) los
defaults son `api_version = "0.1.0-dev"`, `commit = "unknown"`,
`date = "unknown"`, `channel = "dev"`. `go_version` y `arch` **no** se inyectan: se
obtienen en ejecución de `runtime.Version()` y `runtime.GOARCH`, así que siempre son
reales aunque falten los `ldflags`.

## GET /v1/capabilities

```json
{
  "transport": "https",
  "platform": "windows",
  "sensors": ["cpu", "maintenance", "memory", "network", "security", "services", "system_info", "volumes"],
  "actuators": ["power_manager"],
  "actuator_details": {
    "power_manager": {
      "actions": ["cancel", "hibernate", "lock", "restart", "shutdown", "sleep", "status"],
      "allowed_actions": ["lock", "restart"],
      "available_actions": ["lock", "restart", "cancel", "status"],
      "default_delay_seconds": 30,
      "hibernate_supported": false
    }
  },
  "management": {
    "remote_update": {
      "enabled": false,
      "readonly_mode": false,
      "allow_in_readonly": false,
      "channel": "stable"
    }
  }
}
```

`allowed_actions` es lo que permite la configuración; `available_actions` es lo que
además el host puede realmente hacer (por ejemplo, `hibernate` desaparece si la
hibernación está deshabilitada en el equipo). **La integración construye entidades
sobre `available_actions`.**

Dos acciones **no** dependen de `allowed_actions` y por eso aparecen en
`available_actions` aunque no se configuren:

- **`status`** está disponible siempre que el actuador esté registrado (es decir,
  fuera de `readonly_mode`; con `readonly_mode: true` el actuador entero desaparece
  de `capabilities.actuators` y `status` con él).
- **`cancel`** está disponible automáticamente cuando `restart` o `shutdown` estén
  permitidos: si puedes programar un apagado, puedes abortarlo. No necesita entrada
  propia en `allowed_actions`. Si ni `restart` ni `shutdown` están permitidos,
  `cancel` no aparece.

## GET /v1/sensors

Envoltorio idéntico al de ha4linux:

```json
{
  "<sensor_id>": {
    "enabled": true,
    "available": true,
    "data": { }
  },
  "<sensor_id_caido>": {
    "enabled": true,
    "available": false,
    "reason": "timeout after 3s"
  }
}
```

### `cpu`

```json
{
  "usage_percent": 12.42,
  "usage_user_percent": 7.11,
  "usage_kernel_percent": 5.31,
  "logical_processors": 8,
  "per_core": [
    { "index": 0, "usage_percent": 18.3 },
    { "index": 1, "usage_percent": 6.9 }
  ],
  "processes": 214,
  "threads": 2431,
  "handles": 98213,
  "window_seconds": 20.004
}
```

Windows no tiene *load average*: por eso el módulo se llama `cpu` y no `cpu_load`,
y el valor principal es porcentaje de uso en la ventana entre dos lecturas.
`per_core` se omite si `modules.cpu.per_core = false`.

### `memory`

```json
{
  "total_kb": 16721234,
  "available_kb": 8123456,
  "used_kb": 8597778,
  "used_percent": 51.42,
  "commit_total_kb": 9123456,
  "commit_limit_kb": 25165824,
  "commit_percent": 36.25
}
```

`total_kb` / `available_kb` / `used_kb` / `used_percent` son los mismos nombres que
en ha4linux, para que la capa de entidades sea simétrica.

### `network`

```json
{
  "total_rx_bytes": 84771223344,
  "total_tx_bytes": 12233445566,
  "rx_kib_window": 412.55,
  "tx_kib_window": 88.10,
  "window_seconds": 20.004,
  "aggregate_mode": "selected",
  "selected_interfaces": ["Ethernet", "Wi-Fi"],
  "interfaces": {
    "Ethernet": {
      "rx_bytes": 84771223344,
      "tx_bytes": 12233445566,
      "rx_kib_window": 412.55,
      "tx_kib_window": 88.10,
      "description": "Intel(R) Ethernet Connection I219-LM",
      "mac": "AA:BB:CC:DD:EE:FF",
      "oper_status": "up",
      "speed_mbps": 1000,
      "type": "ethernet"
    }
  }
}
```

Payload deliberadamente idéntico al de ha4linux salvo los cuatro campos
descriptivos añadidos por interfaz, que en Linux no estaban disponibles sin coste.
Las claves de interfaz son el **alias** de la NIC (`Ethernet`, `Wi-Fi`), que es lo
que ve el usuario, no el GUID. Los patrones `include_interfaces` /
`exclude_interfaces` se evalúan con comodines de shell sobre ese alias.

### `volumes`

```json
{
  "volumes_total": 2,
  "volumes_readonly": 0,
  "volumes_over_90": 1,
  "volumes": [
    {
      "mountpoint": "C:",
      "label": "Windows",
      "fs_type": "NTFS",
      "drive_type": "fixed",
      "readonly": false,
      "total_bytes": 511000000000,
      "used_bytes": 470000000000,
      "free_bytes": 41000000000,
      "total_gib": 475.91,
      "used_gib": 437.72,
      "free_gib": 38.18,
      "used_percent": 91.98
    }
  ]
}
```

Equivalente de `filesystem` en ha4linux, renombrado a `volumes` porque en Windows
"filesystem" es NTFS/ReFS, no el punto de montaje. Los nombres de campo por volumen
(`used_percent`, `used_gib`, `free_gib`) se mantienen para reutilizar la lógica de
entidades. `mountpoint` es la letra con dos puntos y sin barra (`C:`), o la ruta del
punto de montaje si el volumen está montado en carpeta.

### `services`

```json
{
  "services_total": 3,
  "services_active": 2,
  "services_failed": 1,
  "services": [
    {
      "name": "Spooler",
      "display_name": "Print Spooler",
      "exists": true,
      "status": "running",
      "start_type": "auto",
      "pid": 3120,
      "is_active": true,
      "is_failed": false,
      "can_stop": true,
      "exit_code": 0
    }
  ]
}
```

`is_failed` sigue la **fórmula normativa única definida en
[MODULES.md](MODULES.md#services)** (detenido + arranque automático +
`win32_exit_code` distinto de `0` y de `1077`). No se reproduce aquí para evitar que
las dos copias diverjan: MODULES es la fuente de verdad. Un servicio detenido con
arranque manual o deshabilitado **no** es un fallo. Un
servicio de la watchlist que no existe **se omite** del array `services` (no se
publica una entrada con `exists: false`), igual que en Linux; el campo `exists` solo
aparece con valor `true` en los servicios sí publicados. La watchlist vacía
deshabilita el módulo.

### `system_info`

```json
{
  "hostname": "PC-TALLER",
  "os_name": "Windows",
  "edition": "Windows 11 Pro",
  "display_version": "23H2",
  "build": "22631.4169",
  "major": 10, "minor": 0, "build_number": 22631, "ubr": 4169,
  "architecture": "amd64",
  "install_date": "2024-02-11T09:31:00Z",
  "boot_time": "2026-08-01T06:12:44Z",
  "uptime_seconds": 187423,
  "domain": "WORKGROUP",
  "domain_joined": false,
  "updates_enabled": true,
  "updates_supported": true,
  "updates_provider": "wua",
  "updates_state": "idle",
  "updates_refresh_in_progress": false,
  "updates_pending_count": 3,
  "updates_pending_security_count": 1,
  "updates_reboot_required": false,
  "updates_last_checked_at": "2026-08-03T04:00:11Z",
  "updates_last_error": null,
  "updates_check_interval_sec": 86400,
  "updates_packages": [
    {
      "title": "2026-07 Cumulative Update for Windows 11 (KB5040123)",
      "kb": "KB5040123",
      "severity": "Critical",
      "size_mb": 812.4,
      "is_security": true
    }
  ],
  "updates_packages_total": 3,
  "updates_packages_truncated": false
}
```

El bloque `updates_*` replica nombre a nombre el de ha4linux (`updates_state`,
`updates_pending_count`, `updates_packages`, `updates_packages_truncated`…), con
los mismos estados: `idle`, `checking`, `disabled`, `unsupported`, `error`. La
semántica también es la misma: comprobación en segundo plano, caché de 24 h y
`checking` hasta la primera muestra válida.

### `maintenance`

```json
{
  "pending_reboot": true,
  "pending_reboot_reasons": ["windows_update", "pending_file_rename"],
  "boot_time": "2026-08-01T06:12:44Z",
  "uptime_seconds": 187423,
  "power_source": "ac",
  "battery_present": true,
  "battery_percent": 87,
  "battery_charging": true,
  "shutdown_pending": false,
  "last_shutdown_reason": null
}
```

Motivos posibles de `pending_reboot_reasons`: `component_based_servicing`,
`windows_update`, `pending_file_rename`, `computer_rename`, `sccm`.

### `security`

```json
{
  "defender": {
    "available": true,
    "antivirus_enabled": true,
    "realtime_protection_enabled": true,
    "signature_age_days": 0,
    "signature_version": "1.417.412.0",
    "last_quick_scan": "2026-08-02T22:14:00Z"
  },
  "firewall": {
    "available": true,
    "domain_enabled": true,
    "private_enabled": true,
    "public_enabled": true
  },
  "bitlocker": {
    "available": false,
    "reason": "module disabled by configuration",
    "volumes": []
  },
  "uac_enabled": true,
  "issues_count": 0
}
```

Cada sub-bloque lleva su propio `available`. Un host donde Defender esté sustituido
por otro antivirus devuelve `defender.available: false` con `reason`, y el sensor
sigue estando `available: true` a nivel de módulo. `issues_count` cuenta las
protecciones que están explícitamente desactivadas, no las desconocidas.

## POST /v1/actuators/power_manager/{action}

Acciones: `status`, `lock`, `sleep`, `hibernate`, `restart`, `shutdown`, `cancel`.

Parámetros aceptados por `restart` y `shutdown`:

| Campo | Tipo | Defecto | Nota |
| --- | --- | --- | --- |
| `delay_seconds` | int | `actuators.power.default_delay_seconds` (30) | 0–86400. Ventana para que el usuario cancele |
| `force` | bool | `false` | Cierra aplicaciones con cambios sin guardar |
| `message` | string | `""` | Texto del aviso al usuario durante la cuenta atrás |

`status`:

```json
{
  "ok": true,
  "allowed_actions": ["lock", "restart"],
  "available_actions": ["lock", "restart", "cancel", "status"],
  "hibernate_supported": false,
  "shutdown_pending": false,
  "active_console_session": { "session_id": 1, "user": "PC-TALLER\\ignacio", "state": "active" },
  "pending_reboot": true
}
```

Acción ejecutada:

```json
{
  "ok": true,
  "action": "restart",
  "delay_seconds": 30,
  "force": false,
  "scheduled_at": "2026-08-03T10:00:00Z",
  "effective_at": "2026-08-03T10:00:30Z",
  "cancellable": true
}
```

**Semántica de `lock`:** el servicio vive en la sesión 0 y no puede invocar
`LockWorkStation` sobre el escritorio del usuario. `lock` se implementa como
`WTSDisconnectSession` de la sesión de consola activa, cuyo efecto visible es el
mismo: la sesión queda bloqueada y el usuario debe reautenticarse. La respuesta lo
declara con `"method": "wts_disconnect"`. Si no hay sesión activa, devuelve
`ok: true` con `"message": "no active console session"`.

## Versionado y compatibilidad

- `api_version` — versión semántica del agente. Arranca en `0.1.0`.
- `schema_version` — versión del contrato. `1.1`.
- `min_integration_version` / `max_integration_version` — rango de versiones de
  `custom_components/ha4win` admitidas. La integración evalúa el rango exactamente
  con el algoritmo ya existente en `custom_components/ha4linux/coordinator.py`
  (`_evaluate_compatibility`, soporte de comodín `x`).

Regla de evolución: añadir campos no rompe el esquema; renombrar o eliminar campos
exige subir `schema_version` y ajustar `min_integration_version`.

## Límites operativos

| Límite | Valor |
| --- | --- |
| Cuerpo máximo de petición | 64 KiB (`413` si se excede) |
| Plazo por sensor | `api.sensor_timeout_sec`, 3 s |
| Plazo total de `/v1/sensors` | 10 s |
| Peticiones concurrentes | 16 (semáforo). El exceso **espera un máximo de 2 s**; si no consigue plaza, `503` |
| Timeout de lectura/escritura HTTP | 15 s / 30 s |

La espera acotada es deliberada: un semáforo tras `net/http` sin plazo dejaría
acumularse goroutines indefinidamente bajo carga, que no es una protección real
frente a DoS. Con el plazo, el exceso se rechaza con `503` en vez de crecer sin
límite.
