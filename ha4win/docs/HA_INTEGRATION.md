# Integración de Home Assistant

Integración custom nueva e independiente en `custom_components/ha4win`. No toca
`custom_components/ha4linux`, que sigue sirviendo a la flota Linux en producción.

## Estructura

```
custom_components/ha4win/
├── __init__.py             # setup de la entrada, dispositivo, servicios
├── manifest.json           # domain ha4win, version, iot_class local_polling
├── const.py                # DOMAIN, versión, claves de configuración, defaults
├── config_flow.py          # alta y opciones
├── api.py                  # cliente HTTP del contrato v1
├── coordinator.py          # DataUpdateCoordinator + evaluación de compatibilidad
├── sensor.py               # entidades de telemetría
├── binary_sensor.py        # estados booleanos
├── button.py               # acciones de power_manager
├── update.py               # entidad update del agente y de la propia integración
├── strings.json
├── translations/es.json
├── update-manifest.json
└── brand/{icon.png,logo.png}
```

`api.py` y `coordinator.py` son portables casi literalmente desde
`custom_components/ha4linux`: el contrato es el mismo, incluida la evaluación del
rango de compatibilidad y el manejo de `HA4LinuxNotSupportedError` para hosts que
no exponen un endpoint. Cambian los nombres de clase y las llamadas específicas de
actuador.

```
PLATFORMS = ["sensor", "binary_sensor", "button", "update"]
DEFAULT_PORT = 8099
DEFAULT_USE_HTTPS = True
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 20
```

`binary_sensor` es la plataforma nueva respecto de ha4linux; no hay `switch` en el
v1 porque no hay actuadores de estado binario.

## Ciclo del coordinator

Por cada refresco: `capabilities`, `version`, `sensors`, `update/status`. Si
`power_manager` está en `capabilities.actuators`, además `power_manager/status`.
Es el mismo patrón del coordinator de ha4linux.

Las entidades se crean **una sola vez**, a partir de las capacidades y del payload
del primer refresco. Un módulo que aparece más tarde requiere recargar la entrada,
igual que en ha4linux.

## Dispositivo

Un host = un `device`.

| Campo | Origen |
| --- | --- |
| `name` | `system_info.hostname` |
| `manufacturer` | `HA4Win` |
| `model` | `system_info.edition` (`Windows 11 Pro`) |
| `sw_version` | `version.api_version` |
| `hw_version` | `system_info.build` |
| `configuration_url` | `https://<host>:<port>/health` |

## Entidades

### Sensores de metadatos

| Entidad | Origen |
| --- | --- |
| API Version | `version.api_version` |
| API Schema Version | `version.schema_version` |
| API Compatibility | evaluación local del rango |
| API Update State | `update.state` |
| Operating System | `system_info.edition` + `display_version` |
| Windows Build | `system_info.build` |
| Uptime | `system_info.uptime_seconds`, `device_class: duration` |
| Last Boot | `system_info.boot_time`, `device_class: timestamp` |

### Telemetría

| Entidad | Unidad | `state_class` |
| --- | --- | --- |
| CPU Usage | `%` | `measurement` |
| CPU Usage User / Kernel | `%` | `measurement` |
| CPU Core `<n>` Usage *(deshabilitada por defecto)* | `%` | `measurement` |
| Memory Used (%) | `%` | `measurement` |
| Memory Used | `kB`, `device_class: data_size` | `measurement` |
| Commit Charge (%) | `%` | `measurement` |
| NIC `<alias>` RX Bytes / TX Bytes | `B`, `data_size` | `total_increasing` |
| NIC `<alias>` RX Window / TX Window | `KiB`, `data_size` | `measurement` |
| Volume `<C:>` Used % | `%` | `measurement` |
| Volume `<C:>` Used GiB / Free GiB | `GiB`, `data_size` | `measurement` |
| Volumes Total / Over 90% | — | `measurement` |
| Service `<nombre>` | estado textual | — |
| Services Total / Running / Failed | — | `measurement` |
| Windows Updates State | textual | — |
| Pending Windows Updates | — | `measurement` |
| Battery | `%`, `device_class: battery` | `measurement` |

Las mismas convenciones de ha4linux: `state_class` correcto para que las
estadísticas de HA funcionen, `total_increasing` en contadores acumulados y
`measurement` en ventanas, valores de CPU redondeados a dos decimales, y los
sensores de metadatos marcados como diagnóstico sin estadísticas.

Los sensores por core se crean con `entity_registry_enabled_default: False`: en un
equipo de 16 hilos serían 16 entidades que casi nadie quiere por defecto.

### Binary sensors

| Entidad | Origen | `device_class` |
| --- | --- | --- |
| Pending Reboot | `maintenance.pending_reboot` | `problem` |
| On AC Power | `maintenance.power_source == "ac"` | `plug` |
| Defender Real-Time Protection | `security.defender.realtime_protection_enabled` | `safety` |
| Firewall Enabled | los tres perfiles activos | `safety` |
| BitLocker Protected | todos los volúmenes protegidos | `safety` |
| API Compatible | evaluación del rango | `problem` (invertido) |

Los de `security` solo se crean si el sub-bloque correspondiente reporta
`available: true`. Cuando el sub-bloque pasa a no disponible en caliente, la
entidad va a `unavailable`, no a `off` — misma decisión que en `amcrest_smd`: un
`off` inventado en una entidad de seguridad es peor que un "no lo sé".

### Buttons

Se crea uno por cada acción presente en `capabilities.actuator_details.power_manager.available_actions`:

- Lock, Sleep, Hibernate, Restart, Shutdown, Cancel Shutdown

`Restart` y `Shutdown` usan `device_class: restart` y llevan el retardo por defecto
del host. Para un apagado con parámetros distintos existe el servicio.

### Entidades `update`

- **HA4Win API** — si el host expone `/v1/update/status` con `enabled: true`.
  Instalar ejecuta `POST /v1/update/check` seguido de `POST /v1/update/apply`, igual
  que en ha4linux. `release_summary` incluye `supports_apply_reason` cuando el
  preflight bloquea.
- **HA4Win Integration** — consulta `custom_components/ha4win/update-manifest.json`
  en GitHub. Informativa, sin reescritura automática, sin depender de HACS.

## Servicios

`ha4win.power_action`

| Campo | Obligatorio | Descripción |
| --- | --- | --- |
| `action` | sí | `lock` \| `sleep` \| `hibernate` \| `restart` \| `shutdown` \| `cancel` |
| `delay_seconds` | no | Cuenta atrás |
| `force` | no | Cierra aplicaciones con cambios sin guardar |
| `message` | no | Aviso mostrado al usuario |
| `device_id` / `entity_id` / `entry_id` / `host` | no | Resolución de destino |

Misma resolución de destino que `ha4linux.send_message`: por target de dispositivo o
entidad, por `host`/`entry_id`, y sin destino se aplica a todas las entradas
cargadas. Existe porque los botones no admiten parámetros libres.

```yaml
action:
  - service: ha4win.power_action
    target:
      device_id: 0123456789abcdef0123456789abcdef
    data:
      action: shutdown
      delay_seconds: 120
      message: Apagado programado por Home Assistant
```

## Notificaciones persistentes

Réplica del comportamiento de ha4linux: cuando `updates_pending_count > 0` se crea
una notificación persistente por host, y se retira al volver a cero. Se añade una
segunda para `pending_reboot`, que en Windows es más relevante que en Linux.

## Opciones de la entrada

`Host`, `Port`, `Token`, `Use HTTPS`, `Verify SSL`, `Scan interval`. Idénticas a
ha4linux, para que el operador no tenga que aprender dos flujos.

El `config_flow` valida contra `GET /v1/version` y **rechaza la entrada si
`platform != "windows"`**, con un mensaje que remite a la integración ha4linux. Es
la protección barata contra apuntar la integración equivocada a un host.

`unique_id` de la entrada: `system_info.hostname` en minúsculas, o `host:port` si no
está disponible.

## Convergencia futura

Si en algún momento interesa una integración multiplataforma única (`ha4os`), el
punto de partida ya está preparado: el campo `platform` de `/v1/version`, el
`schema_version` compartido y la simetría deliberada de nombres de campo entre
`memory`, `network`, `volumes`/`filesystem` y `services`.

Esa convergencia implicaría migrar entradas y `unique_id` de los hosts Linux ya
desplegados, así que **no se plantea hasta que ha4win esté validado en producción**.
Mientras tanto, la duplicación de la capa de entidades es el precio consciente de no
tocar una integración que funciona.
