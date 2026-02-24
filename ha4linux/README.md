# HA4Linux Workstation API Add-on

Add-on modular para Home Assistant orientado a monitorizacion y control operativo de sistemas Linux tratados como un dispositivo con entidades.

## Estado actual

Version inicial funcional `0.2.0` con:

- Sensores minimos: `cpu_load`, `memory`, `network`.
- Actuador minimo: `session_manager` para sesion grafica activa (`status`, `activate`, `terminate`).
- Seguridad de transporte: TLS configurable (`tls_enabled`, `tls_certfile`, `tls_keyfile`).
- Seguridad de API: token Bearer (`api_token`).

## Entidades objetivo en Home Assistant

- Un host Linux = `device`.
- Sensores = entidades de telemetria.
- Actuadores = entidades tipo switch/button para acciones controladas.

## Requisitos para actuar sobre sesiones Linux

Para acciones de sesion se recomienda ejecutar los comandos con un usuario dedicado (`ha4linux`) y permisos `sudo` acotados.

### Ejemplo de usuario/grupo

```bash
sudo groupadd --system ha4linux
sudo useradd --system --gid ha4linux --home /var/lib/ha4linux --shell /usr/sbin/nologin ha4linux
```

### Ejemplo de sudoers minimo

```sudoers
Cmnd_Alias HA4LINUX_SESSION = /usr/bin/loginctl activate *, /usr/bin/loginctl terminate-session *
ha4linux ALL=(root) NOPASSWD: HA4LINUX_SESSION
Defaults:ha4linux !requiretty
```

## API basica

- `GET /health`
- `GET /v1/capabilities`
- `GET /v1/sensors`
- `POST /v1/actuators/session_manager/status`
- `POST /v1/actuators/session_manager/activate`
- `POST /v1/actuators/session_manager/terminate`

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
