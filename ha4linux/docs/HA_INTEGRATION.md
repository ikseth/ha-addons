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

- CPU Load 1m
- CPU Load 5m
- Memory Used (%)
- Memory Used KB
- Network RX Bytes
- Network TX Bytes
- Network RX Window (KiB)
- Network TX Window (KiB)
- App Policies Total
- App Policy Violations

Compatibilidad con estadisticas de Home Assistant:

- `CPU Load 1m`, `CPU Load 5m`, `Memory Used` y `Memory Used KB` usan `state_class=measurement`.
- `Network RX Bytes` y `Network TX Bytes` usan `device_class=data_size`, unidad `B` y `state_class=total_increasing`.
- `Network RX Window` y `Network TX Window` usan `device_class=data_size`, unidad `KiB` y `state_class=measurement`.
- Los valores de CPU se publican con precision de 2 decimales.
- Los sensores `Network * Window` representan el delta agregado de trafico en la ventana entre lecturas (normalmente `scan_interval`).

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
