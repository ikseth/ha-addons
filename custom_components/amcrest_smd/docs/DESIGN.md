# Amcrest SMD — diseño

Integración de Home Assistant que expone la **detección inteligente (SMD)** de
cámaras Amcrest/Dahua como sensores binarios: persona y vehículo, diferenciados
del movimiento genérico.

Verificada contra una `IP5M-T1179EB-AI-V3` (internamente Dahua `IPC-HFW2541SP-S`,
gama WizSense "Lite AI"), firmware `2.880.00AC003.0.R`.

## Por qué existe

La cámara ya distingue personas de vehículos y de movimiento cualquiera, pero ni
la integración ONVIF ni la antigua integración YAML `amcrest` exponen esa
información: ambas se quedan en "hay movimiento".

Medido sobre 34 h de datos reales correlacionando el log interno de la cámara con
el historial de HA: **el 33 % de las activaciones de movimiento que ve HA no
corresponden ni a una persona ni a un vehículo**. Filtrar por SMD elimina ese
ruido.

## Arquitectura: push, no sondeo

La cámara ofrece dos formas de conocer el estado SMD:

| Vía | Coste |
| --- | --- |
| `getEventIndexes` en bucle | ~8.600 peticiones/día (×2 por el reto Digest) |
| `eventManager.cgi?action=attach` | **1 conexión persistente**, 0 tráfico en reposo |

Se usa la segunda. Es una única conexión HTTP `multipart/x-mixed-replace` que la
cámara mantiene abierta y por la que empuja cada evento en el instante en que
ocurre. Cuando no pasa nada, no viaja nada.

El parámetro `heartbeat` hace que la cámara emita un keepalive periódico por esa
misma conexión. Sirve para distinguir "no está pasando nada" de "la conexión está
muerta": si no llega ni evento ni heartbeat en 3 intervalos, se reconecta.

### Formato del protocolo

Verificado empíricamente sobre el dispositivo:

```
--myboundary\r\n
Content-Type: text/plain\r\n
Content-Length: 47\r\n
\r\n
Code=SmartMotionHuman;action=Start;index=0;data={...}
```

El cuerpo se lee por `Content-Length` y no buscando el separador, porque el JSON
de `data` contiene saltos de línea.

### Una sola consulta al conectar

Al establecer la conexión se hace **una** llamada a `getEventIndexes` por cada
código vigilado, para inicializar el estado y no quedar a ciegas hasta el
siguiente evento. Es una petición por conexión, no un sondeo periódico.

### Reconexión

Backoff exponencial (1 s, 2 s, 4 s… hasta 60 s) para no martillear la cámara
mientras esté caída. El contador se reinicia tras una conexión buena, de modo que
una caída puntual se recupera de inmediato pero una cámara apagada no recibe
miles de intentos. Un fallo de credenciales salta directamente al tope: reintentar
rápido no arregla una contraseña mala.

## Decisiones de diseño deliberadas

### 1. No hay watchdog de eventos colgados

Si se pierde el evento `Stop` (por ejemplo, si la conexión cae justo entre el
`Start` y el `Stop`), el sensor **permanece en `on`** hasta el siguiente `Stop`.

Es una limitación conocida y compartida con otros sensores de presencia del
mercado. Se decidió no añadir un temporizador de seguridad aquí, sino compensarlo
en la capa de automatismos combinando esta señal con sensores PIR independientes.

**Quien consuma estas entidades debe asumir este contrato.**

### 2. Al caer la conexión, `unavailable` — nunca un `off` inventado

Los sensores de detección quedan `unavailable` cuando el stream está caído. No se
degradan a `off`.

El motivo es de seguridad: un `off` falso con una persona dentro del garaje
apagaría las luces, y lo haría de forma silenciosa. Es preferible un estado
honesto de "no lo sé" que un estado cómodo pero falso.

La contrapartida es que **cada consumidor debe tratar `unavailable` de forma
explícita**. En particular, un disparador `from: 'on'` `to: 'off'` no se activa
en una transición `on → unavailable → off`.

`binary_sensor.*_conexion_de_eventos` se mantiene siempre disponible: es la
entidad que dice la verdad sobre si las demás son fiables en este momento.

### 3. Se engancha al dispositivo existente de ONVIF

Si se puede leer la MAC de la cámara, se declara como conexión de red, con lo que
HA fusiona estas entidades con el dispositivo que ya creó la integración ONVIF en
lugar de duplicarlo.

El manifest declara `after_dependencies: ["onvif"]`, no `dependencies`: es una
ordenación blanda. Si ONVIF está, se carga antes y el dispositivo llega con su
metadata completa; si no está, esta integración funciona igualmente por su cuenta.

## Entidades

| Entidad | Clase | Origen |
| --- | --- | --- |
| `*_persona_detectada` | `motion` | `Code=SmartMotionHuman` |
| `*_vehiculo_detectado` | `motion` | `Code=SmartMotionVehicle` |
| `*_conexion_de_eventos` | `connectivity`, diagnóstico | estado del stream |

## Requisitos en la cámara

- SMD activo con los tipos de objeto deseados:
  `configManager.cgi?action=getConfig&name=SmartMotionDetect` debe mostrar
  `Enable=true` y `ObjectTypes.Human=true` / `ObjectTypes.Vehicle=true`.
- Un usuario con permiso de monitorización. Para el stream y la consulta inicial
  bastan `Monitor_01` y `AuthSysInfo`; **no** se requiere ningún permiso de
  escritura. La lectura de la MAC necesita además permiso de red y es
  best-effort: si falla, la integración sigue funcionando con dispositivo propio.

## Validación

### Antes del despliegue

- Parser multipart contra bytes reales capturados de la cámara, incluyendo
  entrega fragmentada byte a byte (TCP parte los eventos por la mitad).
- `parse_event` con eventos SMD reales y con heartbeats.
- **Autenticación Digest contra la cámara real**, que es la pieza de más riesgo
  por implementarse sin dependencias externas.

### En producción (2026-07-30)

**Detección real**, con una persona caminando por el garaje:

```
12:17:35  camara_garaje_movimiento (ONVIF, generico)  -> on
12:17:40  persona_detectada                           -> on
12:18:19  persona_detectada                           -> off
          vehiculo_detectado                          -> off  (correcto)
```

Ciclo `Start`/`Stop` completo de 39 s. Los ~4 s de retraso frente al movimiento
genérico son de la cámara clasificando el objeto, no de la integración.

**Resiliencia**, reiniciando la cámara desde `button.amcrest_reboot`:

```
10:58:07  reboot enviado
10:58:48  conexion=off   persona=unavailable   (detectado por timeout de lectura)
10:59:21  conexion=on    persona=off           (reconectado y estado resincronizado)
```

33 s de corte, recuperado sin intervención. `persona` pasó a `unavailable` y no a
`off`, confirmando la decisión de diseño bajo un fallo real.

**Estabilidad**: 10 minutos continuados sin una sola caída antes de forzar el
reinicio, lo que confirma que el heartbeat fluye y que el timeout de lectura está
bien dimensionado.

**Ciclo de vida**: recarga de la entrada en caliente (`require_restart: false`)
con parada ordenada y reconexión automática.

**Fusión de dispositivo**: las entidades quedan en el dispositivo `amc-01` que ya
existía por ONVIF, heredando su área, sin crear un duplicado.

### Defecto encontrado y corregido en esta validación

La primera prueba de reinicio destapó que la desconexión emergía como
`aiohttp.SocketTimeoutError` sin capturar, y se registraba como error inesperado
con traza completa. Funcionalmente recuperaba bien, pero el ruido en el log era
incorrecto: un reinicio de cámara es una desconexión esperable. Ahora se traduce a
`AmcrestSmdApiError` y se registra en una línea de INFO, y sólo la primera vez
tras una conexión buena.
