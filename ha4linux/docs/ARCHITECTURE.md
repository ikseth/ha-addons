# Arquitectura modular ha4linux

## Bloques

- Core API: autenticacion, TLS, registro de modulos y endpoints estables `v1` (incluyendo metadata de version/compatibilidad).
- Sensores: recolectan telemetria y reportan `available/unavailable`.
- Actuadores: ejecutan acciones permitidas sobre el sistema operativo.

## Modelo funcional

- Linux host se modela como un `device` en Home Assistant.
- Cada sensor se mapea a una entidad de tipo sensor.
- Cada actuador se mapea a entidades de accion o a servicios cuando necesita payload libre.

## Contrato de modulo

### Sensor

- `id`
- `collect() -> dict`

### Actuador

- `id`
- `execute(action, params) -> dict`

## Modulos incluidos

### Sensores

- `cpu_load`: carga media y numero de CPUs.
- `memory`: memoria total/disponible/usada.
- `network`: trafico RX/TX total e interfaces.
- `network` soporta filtrado declarativo por interfaz y deltas por interfaz para HA.
- `raid_mdstat`: estado de arrays Linux MD (`/proc/mdstat`).
- `virtualbox`: estado de VMs de VirtualBox para un usuario configurado.
- `services`: estado de servicios `systemd` de una watchlist configurable.
- `app_policies`: estado de politicas por aplicacion (running/violating/allowed).

### Actuadores

- `session_manager`: `status`, `activate`, `terminate` sobre sesiones graficas (`x11`/`wayland`).
- `app_policy`: `status`, `allow`, `block`, `enforce`, `reload` para control generico de apps.
- `message_dispatcher`: `send` para mensajeria remota por `broadcast` y/o `x11`.
- `virtualbox_manager`: acciones por VM (`start`, `acpi_shutdown`, `savestate`; `poweroff/reset` solo si se habilitan).

## Politicas de aplicaciones

Fuente declarativa en fichero JSON (`HA4LINUX_APP_POLICY_FILE`), con estructura:

- `id`: identificador estable.
- `process_names`: procesos a vigilar/bloquear.
- `service_names`: servicios a vigilar/bloquear.
- `allowed`: permitido/bloqueado.
- `action_on_block`: `terminate` | `stop_service` | `none`.
- `monitor_only`: solo observacion.

## Seguridad

- API protegida por Bearer token.
- TLS configurable para transporte seguro.
- Operaciones sensibles mediante `sudo -n` y politica de `sudoers` restringida.
- Allowlist opcional de usuarios de sesion (`allowed_session_users`).
- Entrega `x11` encapsulada en un helper root local para inspeccionar sesion y ejecutar `notify-send`/`xmessage` con el usuario grafico correcto.
- Allowlist opcional de VMs y acciones para VirtualBox (`actuators.virtualbox.*`).

## Configuracion

- Cliente Linux: JSON estructurado en `/etc/ha4linux/config.json`.
- Bootstrap/compatibilidad: `HA4LINUX_CONFIG_FILE` y variables legacy `HA4LINUX_*`.
- Add-on HA: `options.json` del supervisor, consumido por el mismo loader.

## Principios

- Modulos habilitables/deshabilitables por configuracion.
- Exposicion condicional: solo se registran modulos con prerequisitos disponibles.
- Fallos aislados: un modulo fallando no derriba el core.
- Superficie de accion minima por defecto.
