# Arquitectura modular ha4linux

## Bloques

- Core API: autenticacion, TLS, registro de modulos y endpoints estables `v1`.
- Sensores: recolectan telemetria y reportan `available/unavailable`.
- Actuadores: ejecutan acciones permitidas sobre el sistema operativo.

## Modelo funcional

- Linux host se modela como un `device` en Home Assistant.
- Cada sensor se mapea a una entidad de tipo sensor.
- Cada actuador se mapea a entidades de accion (switch/button).

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

### Actuadores

- `session_manager`: `status`, `activate`, `terminate` sobre sesiones graficas (`x11`/`wayland`).

## Seguridad

- API protegida por Bearer token.
- TLS configurable para transporte seguro.
- Operaciones sensibles mediante `sudo -n` y politica de `sudoers` restringida.
- Allowlist opcional de usuarios de sesion (`allowed_session_users`).

## Principios

- Modulos habilitables/deshabilitables por configuracion.
- Fallos aislados: un modulo fallando no derriba el core.
- Superficie de accion minima por defecto.
