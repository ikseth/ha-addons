# Integracion instalable en Home Assistant

Se incluye una integracion custom en:

- `custom_components/ha4linux`

## Instalacion manual

1. Copiar carpeta al config de Home Assistant:

```bash
cp -r custom_components/ha4linux /config/custom_components/
```

2. Reiniciar Home Assistant.

3. Ir a `Ajustes > Dispositivos y servicios > Añadir integracion`.

4. Buscar `HA4Linux` y completar:

- Host: `192.168.59.202`
- Port: `8099`
- Token API
- HTTPS: activado
- Verify SSL: segun tu certificado

## Entidades creadas

Sensores:

- API Version
- API Schema Version
- API Compatibility
- API Update State
- Operating System
- Package Manager
- Package Updates State
- Pending Package Updates
- CPU Load 1m
- CPU Load 5m
- Memory Used (%)
- Memory Used KB
- RAID Arrays Total
- RAID Arrays Degraded
- RAID Arrays Rebuilding
- VirtualBox VMs Total
- VirtualBox VMs Running
- Services Total
- Services Active
- Services Failed
- Filesystems Total
- Filesystems Readonly
- Filesystems Over 90%
- App Policies Total
- App Policy Violations

Entidad `update` (si el host expone `/v1/update/status` y `enabled=true`):

- `HA4Linux API` (instalar update desde HA)

Entidad `update` adicional para la propia integracion custom:

- `HA4Linux Integration` (deteccion de nueva version publicada en el repositorio GitHub de origen)

Sensores dinamicos por recurso (si el modulo esta disponible):

- RAID `<mdX>` (estado y atributos de discos).
- Service `<unit.service>` (estado `systemd`).
- VM `<name>` (estado VirtualBox).
- NIC `<ifname>` RX Bytes
- NIC `<ifname>` TX Bytes
- NIC `<ifname>` RX Window
- NIC `<ifname>` TX Window
- FS `<mountpoint>` Used %
- FS `<mountpoint>` Used GiB
- FS `<mountpoint>` Free GiB

Compatibilidad con estadisticas de Home Assistant:

- `CPU Load 1m`, `CPU Load 5m`, `Memory Used` y `Memory Used KB` usan `state_class=measurement`.
- `NIC * RX Bytes` y `NIC * TX Bytes` usan `device_class=data_size`, unidad `B` y `state_class=total_increasing`.
- `NIC * RX Window` y `NIC * TX Window` usan `device_class=data_size`, unidad `KiB` y `state_class=measurement`.
- Los contadores resumen de RAID/VirtualBox/Services/Filesystem usan `state_class=measurement`.
- `FS <mountpoint> Used %` usa `state_class=measurement`.
- `FS <mountpoint> Used GiB` y `FS <mountpoint> Free GiB` usan `device_class=data_size`, unidad `GiB` y `state_class=measurement`.
- Los valores de CPU se publican con precision de 2 decimales.
- Los sensores `NIC * Window` representan el delta por interfaz en la misma ventana entre lecturas.
- Los sensores de metadata (`API Version`, `API Schema Version`, `API Compatibility`, `API Update State`) son informativos y no se usan para estadisticas.

Switch (si el actuador existe):

- Active Graphical Session
- App Allowed `<app_id>` (uno por cada app declarada en politicas)
- VM `<name>` Power (si `virtualbox_manager` permite `start` y la accion de apagado configurada)

Buttons dinamicos por VM (si `virtualbox_manager` los permite):

- VM `<name>` Start
- VM `<name>` Graceful Shutdown
- VM `<name>` Save State
- VM `<name>` Force Power Off
- VM `<name>` Reset

Servicio registrado por la integracion:

- `ha4linux.send_message`

`ON` intenta activar sesion grafica.
`OFF` intenta terminar sesion grafica activa.

En switches de apps:

- `ON` => `allow` (permitir app)
- `OFF` => `block` (bloquear app)

## Servicio `ha4linux.send_message`

Permite enviar mensajes arbitrarios a uno o varios hosts HA4Linux sin crear nuevas entidades.

Campos soportados:

- `message` obligatorio
- `title` opcional
- `delivery` opcional (`broadcast`, `x11`)
- `host` opcional
- `entry_id` opcional
- `device_id` / `entity_id` opcionales via target del servicio

Resolucion de destino:

- Si usas target sobre dispositivo o entidad, el servicio resuelve automaticamente el host HA4Linux asociado.
- Si no indicas target ni `host`/`entry_id`, la llamada se envia a todas las entradas HA4Linux cargadas.

Ejemplo de automatizacion:

```yaml
action:
  - service: ha4linux.send_message
    target:
      device_id:
        - 0123456789abcdef0123456789abcdef
    data:
      title: Home Assistant
      message: Mantenimiento programado en 10 minutos.
      delivery:
        - broadcast
```

Notas:

- La integracion delega la entrega real en el actuator remoto `message_dispatcher`.
- Un host antiguo que no exponga este actuator devolvera error de servicio para ese destino.

## Opciones

Desde la entrada de integracion:

- `Host`
- `Port`
- `Token API`
- `Use HTTPS`
- `Verify SSL`
- `Scan interval` (segundos)

Notas de update remoto:

- La comprobacion de disponibilidad de nuevas versiones la gobierna el host API (`HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC`).
- La accion de instalar desde la entidad `update` ejecuta `POST /v1/update/check` y `POST /v1/update/apply`.

Notas de update de la integracion custom:

- La integracion consulta `custom_components/ha4linux/update-manifest.json` en el repositorio GitHub origen.
- No depende de HACS.
- Esta entidad es informativa: detecta y propone la actualizacion de la integracion, pero no reescribe automaticamente `/config/custom_components/ha4linux`.
- Para publicar una nueva version detectable debes actualizar estos ficheros del componente:
  - `custom_components/ha4linux/const.py`
  - `custom_components/ha4linux/manifest.json`
  - `custom_components/ha4linux/update-manifest.json`

Notas de updates del sistema:

- El modulo `system_info` expone distribucion, version, kernel y gestor de paquetes del host Linux.
- La comprobacion de paquetes pendientes se ejecuta en el host y queda cacheada por defecto durante `86400` segundos.
- El refresco de paquetes se lanza en segundo plano para no bloquear el poll de Home Assistant; hasta disponer de una muestra valida, el estado expuesto sera `checking`.
- Cuando el host devuelve `updates_pending_count > 0`, la integracion crea una notificacion persistente en Home Assistant.
- La comprobacion es best effort y actualmente soporta `apt`, `dnf`, `yum`, `zypper` y `pacman/checkupdates` si estan disponibles.
