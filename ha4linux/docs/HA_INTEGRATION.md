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

Switch (si el actuador existe):

- Active Graphical Session

`ON` intenta activar sesion grafica.
`OFF` intenta terminar sesion grafica activa.

## Opciones

Desde la entrada de integracion:

- `Scan interval` (segundos)
