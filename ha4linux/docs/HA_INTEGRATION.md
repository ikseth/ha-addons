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
- CPU Load 1m
- CPU Load 5m
- Memory Used (%)
- Memory Used KB
- Network RX Bytes
- Network TX Bytes
- Network RX Window (KiB)
- Network TX Window (KiB)
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
- `Network RX Bytes` y `Network TX Bytes` usan `device_class=data_size`, unidad `B` y `state_class=total_increasing`.
- `Network RX Window` y `Network TX Window` usan `device_class=data_size`, unidad `KiB` y `state_class=measurement`.
- `NIC * RX Bytes` y `NIC * TX Bytes` usan `device_class=data_size`, unidad `B` y `state_class=total_increasing`.
- `NIC * RX Window` y `NIC * TX Window` usan `device_class=data_size`, unidad `KiB` y `state_class=measurement`.
- Los contadores resumen de RAID/VirtualBox/Services/Filesystem usan `state_class=measurement`.
- `FS <mountpoint> Used %` usa `state_class=measurement`.
- `FS <mountpoint> Used GiB` y `FS <mountpoint> Free GiB` usan `device_class=data_size`, unidad `GiB` y `state_class=measurement`.
- Los valores de CPU se publican con precision de 2 decimales.
- Los sensores `Network * Window` representan el delta agregado de trafico en la ventana entre lecturas (normalmente `scan_interval`).
- Los sensores `NIC * Window` representan el delta por interfaz en la misma ventana entre lecturas.
- Si el host API filtra interfaces, los sensores agregados de red reflejan el modo de agregado configurado en ese host (`selected` o `all`).
- Los sensores de metadata (`API Version`, `API Schema Version`, `API Compatibility`, `API Update State`) son informativos y no se usan para estadisticas.

Switch (si el actuador existe):

- Active Graphical Session
- App Allowed `<app_id>` (uno por cada app declarada en politicas)

`ON` intenta activar sesion grafica.
`OFF` intenta terminar sesion grafica activa.

En switches de apps:

- `ON` => `allow` (permitir app)
- `OFF` => `block` (bloquear app)

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
