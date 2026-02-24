# Testing seguro (entorno HA productivo)

Objetivo: validar la API en `192.168.59.202` minimizando impacto en HA `192.168.60.30`.

## Fase 0: conectividad (no intrusiva)

Desde una maquina con red a ambos hosts:

```bash
ping -c 1 192.168.59.202
ping -c 1 192.168.60.30
nc -zv 192.168.59.202 8099
nc -zv 192.168.60.30 8123
```

## Fase 1: desplegar API en cliente Linux

En `192.168.59.202`, ejecutar con TLS y token:

```bash
docker run -d --name ha4linux \
  -p 8099:8099 \
  -e HA4LINUX_API_TOKEN='<TOKEN_SEGURA>' \
  -e HA4LINUX_TLS_ENABLED='true' \
  -e HA4LINUX_TLS_CERTFILE='/ssl/fullchain.pem' \
  -e HA4LINUX_TLS_KEYFILE='/ssl/privkey.pem' \
  -e HA4LINUX_ALLOWED_SESSION_USERS='usuario1,usuario2' \
  -v /ruta/certs:/ssl:ro \
  <imagen_ha4linux>:0.2.0
```

Nota: si aun no tienes PKI lista, para prueba puntual puedes usar `HA4LINUX_TLS_ENABLED='false'` solo en red aislada.

## Fase 2: smoke test (solo lectura por defecto)

Desde HA server (`192.168.60.30`) o desde otra maquina de admin:

```bash
cd /ruta/al/repo/ha-addons
./ha4linux/scripts/smoke_test_api.sh https://192.168.59.202:8099 '<TOKEN_SEGURA>' --insecure
```

- `--insecure` evita fallo por certificado no confiado durante pruebas.
- Sin `--with-actuation`, no ejecuta acciones intrusivas.

## Fase 3: prueba de actuador (controlada)

Solo cuando se autorice:

```bash
./ha4linux/scripts/smoke_test_api.sh https://192.168.59.202:8099 '<TOKEN_SEGURA>' --insecure --with-actuation
```

Esto intenta `terminate` de la sesion grafica activa.

## Recomendacion para HA productivo

- Primero integrar solo sensores (lectura).
- Actuadores deshabilitados hasta validar permisos y efectos.
- Ejecutar pruebas de actuacion fuera de horario de operacion.
