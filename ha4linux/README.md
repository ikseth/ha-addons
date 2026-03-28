# HA4Linux Workstation API Add-on

Add-on modular para Home Assistant orientado a monitorizacion y control operativo de sistemas Linux tratados como un dispositivo con entidades.

## Estado actual

Version funcional `0.5.6` con:

- Sensores base: `cpu_load`, `memory`, `network`.
- Sensores de infraestructura: `raid_mdstat`, `virtualbox`, `services`.
- Sensor de almacenamiento local: `filesystem` (sin FS de red por defecto).
- Sensor de sistema: `system_info` (distro/kernel/gestor de paquetes y updates pendientes cacheadas).
- Sensor modular de politicas de apps: `app_policies`.
- Actuador de sesion grafica: `session_manager` (`status`, `activate`, `terminate`).
- Actuador modular de politicas de apps: `app_policy` (`status`, `allow`, `block`, `enforce`, `reload`).
- Actuador de VirtualBox: `virtualbox_manager` (`status`, `start`, `acpi_shutdown`, `savestate`, con acciones peligrosas opt-in).
- Gestion remota de actualizaciones (opcional y desactivada por defecto): `/v1/update/*`.
- Ultima milla de actualizacion remota: manifiesto con artefacto y checksum, helper local con backup y rollback.
- Seguridad de transporte: TLS configurable (`tls_enabled`, `tls_certfile`, `tls_keyfile`).
- Seguridad de API: token Bearer (`api_token`).
- Configuracion estructurada por JSON en cliente Linux, con compatibilidad hacia atras para `env`.
- Modo de solo lectura para entornos criticos (`readonly_mode`).

## Entidades objetivo en Home Assistant

- Un host Linux = `device`.
- Sensores = entidades de telemetria.
- Actuadores = entidades tipo switch/button para acciones controladas.

## Control de apps (declarativo)

El control es generico por politica declarativa (JSON), no hardcodeado a una app concreta.
Por defecto, el instalador crea `apps.json` vacio y solo se exponen controles para apps que declares explicitamente.

Ruta por defecto en add-on:

- `/data/app_policies.json`

Ruta por defecto en instalador Linux:

- `/etc/ha4linux/policies/apps.json`

Ejemplo de politica (opcional):

```json
{
  "apps": [
    {
      "id": "kodi",
      "process_names": ["kodi.bin", "kodi"],
      "service_names": [],
      "allowed": true,
      "action_on_block": "terminate",
      "monitor_only": false
    }
  ]
}
```

Semantica:

- `allowed=true`: la app esta permitida.
- `allowed=false`: la app queda bloqueada.
- `action_on_block=terminate`: termina procesos detectados.
- `action_on_block=stop_service`: intenta parar servicios declarados via `sudo -n systemctl stop`.
- `monitor_only=true`: solo monitoriza, sin aplicar bloqueo.

## API basica

- `GET /health`
- `GET /v1/version`
- `GET /v1/capabilities`
- `GET /v1/sensors`
- `GET /v1/update/status`
- `POST /v1/update/check`
- `POST /v1/update/apply`
- `POST /v1/update/rollback`
- `POST /v1/actuators/session_manager/status`
- `POST /v1/actuators/session_manager/activate`
- `POST /v1/actuators/session_manager/terminate`
- `POST /v1/actuators/app_policy/status`
- `POST /v1/actuators/app_policy/allow`
- `POST /v1/actuators/app_policy/block`
- `POST /v1/actuators/app_policy/enforce`
- `POST /v1/actuators/app_policy/reload`
- `POST /v1/actuators/virtualbox_manager/status`
- `POST /v1/actuators/virtualbox_manager/start`
- `POST /v1/actuators/virtualbox_manager/acpi_shutdown`
- `POST /v1/actuators/virtualbox_manager/savestate`
- `POST /v1/actuators/virtualbox_manager/poweroff`
- `POST /v1/actuators/virtualbox_manager/reset`

`GET /v1/version` expone metadatos de version y rango de compatibilidad de la integracion HA:

- `api_version`
- `schema_version`
- `min_integration_version`
- `max_integration_version`
- `build` (`commit`, `date`, `channel`)

`/v1/update/*` permite comprobacion/aplicacion de updates desde HA bajo estas condiciones:

- `HA4LINUX_REMOTE_UPDATE_ENABLED=true`
- `HA4LINUX_REMOTE_UPDATE_MANIFEST_URL` configurada
- `HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND` (para instalar) y opcionalmente `...ROLLBACK_COMMAND`

Por seguridad:

- Esta funcionalidad esta desactivada por defecto.
- Si `readonly_mode=true`, update/rollback quedan bloqueados salvo que `HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY=true`.

`filesystem` expone por mountpoint:

- `used_percent`
- `used_gib`
- `free_gib`

`system_info` expone:

- distribucion Linux detectada via `/etc/os-release`
- version y codename de la distribucion
- kernel y arquitectura
- gestor de paquetes detectado
- numero de updates de sistema pendientes y preview de paquetes

La comprobacion de updates de sistema se ejecuta localmente en el host y se cachea por defecto durante 24 horas para evitar sondeos pesados en cada poll de Home Assistant. El refresco se lanza en segundo plano para no bloquear `GET /v1/sensors`; mientras no exista una muestra valida, el estado expuesto sera `checking`. La deteccion actual es best effort para `apt`, `dnf`, `yum`, `zypper` y `pacman/checkupdates`.

Con filtros configurables:

- `HA4LINUX_FILESYSTEM_EXCLUDE_TYPES`
- `HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS`

`network` expone:

- Contadores agregados RX/TX (`total_*` y `*_kib_window`).
- Contadores diferenciados por interfaz en `interfaces`.
- Seleccion declarativa de interfaces via `include_interfaces` y `exclude_interfaces`.
- Modo de agregado `selected|all` para decidir si el resumen usa solo las interfaces elegidas o todas las disponibles.

## Modelo de configuracion

En cliente Linux la configuracion principal pasa a ser JSON estructurado en:

- `/etc/ha4linux/config.json`

El servicio `systemd` mantiene un bootstrap minimo en:

- `/etc/ha4linux/ha4linux.env`

Precedencia efectiva:

- variables `HA4LINUX_*`
- `config.json`
- defaults internos

## Requisitos para acciones privilegiadas

### Sesion grafica

```sudoers
Cmnd_Alias HA4LINUX_SESSION = /usr/bin/loginctl activate *, /usr/bin/loginctl terminate-session *
ha4linux ALL=(root) NOPASSWD: HA4LINUX_SESSION
Defaults:ha4linux !requiretty
```

### Politicas con stop de servicios

```sudoers
Cmnd_Alias HA4LINUX_APPS = /usr/bin/systemctl stop *
ha4linux ALL=(root) NOPASSWD: HA4LINUX_APPS
Defaults:ha4linux !requiretty
```

## Notas de despliegue

- Si `tls_enabled=true`, los ficheros de certificado deben existir.
- En Home Assistant Add-on se mapea `/ssl` de solo lectura para usar certificados del sistema.
- El control de sesiones depende de disponer de `loginctl` y permisos de sistema adecuados en el entorno donde corra el API.

## Instalador Linux cliente

Se incluye instalador multi-distro y empaquetado nativo en:

- `packaging/common/install-client.sh`
- `packaging/scripts/build-deb.sh`
- `packaging/scripts/build-rpm.sh`
- `packaging/scripts/build-arch.sh`

Guia: `docs/CLIENT_INSTALLER.md`.
