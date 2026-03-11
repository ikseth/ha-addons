# HA4Linux Workstation API Add-on

Add-on modular para Home Assistant orientado a monitorizacion y control operativo de sistemas Linux tratados como un dispositivo con entidades.

## Estado actual

Version funcional `0.3.0` con:

- Sensores base: `cpu_load`, `memory`, `network`.
- Sensores de infraestructura: `raid_mdstat`, `virtualbox`, `services`.
- Sensor modular de politicas de apps: `app_policies`.
- Actuador de sesion grafica: `session_manager` (`status`, `activate`, `terminate`).
- Actuador modular de politicas de apps: `app_policy` (`status`, `allow`, `block`, `enforce`, `reload`).
- Seguridad de transporte: TLS configurable (`tls_enabled`, `tls_certfile`, `tls_keyfile`).
- Seguridad de API: token Bearer (`api_token`).
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
- `POST /v1/actuators/session_manager/status`
- `POST /v1/actuators/session_manager/activate`
- `POST /v1/actuators/session_manager/terminate`
- `POST /v1/actuators/app_policy/status`
- `POST /v1/actuators/app_policy/allow`
- `POST /v1/actuators/app_policy/block`
- `POST /v1/actuators/app_policy/enforce`
- `POST /v1/actuators/app_policy/reload`

`GET /v1/version` expone metadatos de version y rango de compatibilidad de la integracion HA:

- `api_version`
- `schema_version`
- `min_integration_version`
- `max_integration_version`
- `build` (`commit`, `date`, `channel`)

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
