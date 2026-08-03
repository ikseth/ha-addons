# Seguridad

## Qué se está exponiendo

Un servicio que corre como **LocalSystem** y escucha en la red. Con
`actuators.power.allowed_actions` ampliado, quien tenga el token puede apagar el
equipo; con `remote_update.enabled` puede además hacer que el host descargue y
ejecute un binario. Ese es el perímetro real y el diseño lo trata como tal.

## Modelo de amenaza

| Amenaza | Mitigación |
| --- | --- |
| Robo del token desde el disco | DACL sin herencia sobre `C:\ProgramData\HA4Win`: solo SYSTEM y Administrators. Un usuario estándar no puede leer `config.json` |
| Token en tránsito | TLS activo por defecto; el token nunca viaja por HTTP salvo desactivación explícita, que además queda registrada en el Event Log |
| Fuerza bruta / *timing* sobre el token | Comparación en tiempo constante (`crypto/subtle`), token de 32 bytes generado con `crypto/rand` |
| Acceso desde host no autorizado | `api.allowed_clients` (CIDR) y regla de firewall limitada a los perfiles Domain y Private |
| Escalada vía actuadores | Todo salvo `lock` y `status` es opt-in; `readonly_mode` desregistra el actuador completo |
| Suplantación del manifiesto de update | `sha256` obligatorio; `require_signed_asset` verifica Authenticode con `WinVerifyTrust`; HTTPS con validación de cadena del sistema |
| Artefacto de update corrupto o incompatible | Arranque de prueba antes del swap, health-check y rollback automático |
| Escalada vía inyección de comandos | No se ejecuta ningún proceso externo con datos de entrada. El único proceso hijo es el propio binario en la actualización, con argumentos fijos |
| Denegación de servicio por peticiones | Cuerpo máximo 64 KiB, timeouts de lectura/escritura, concurrencia acotada |
| Fuga de información en respuestas | `config print` censura el token; los payloads de sensores no incluyen credenciales ni rutas de usuario |

## Decisiones deliberadas

### LocalSystem y no una cuenta de servicio dedicada

En Linux se creó el usuario `ha4linux` y se le dieron permisos puntuales con
`sudoers`. En Windows el equivalente sería una cuenta de servicio con privilegios
asignados, pero **las operaciones del v1 requieren de todos modos privilegios de
sistema** (consultar el SCM, apagar, WUA), así que una cuenta intermedia añadiría
complejidad de instalación sin reducir el privilegio efectivo.

La compensación es que el alcance se limita **por configuración** y no por
permisos: superficie mínima por defecto y todo lo destructivo desactivado.

Alternativa evaluada y descartada para el v1: `NT SERVICE\ha4win` (virtual service
account) con privilegios concretos. Es más correcto y queda anotado como mejora de
la fase 6, condicionada a comprobar que WUA y el SCM funcionan sin LocalSystem.

### Sin `LockWorkStation`

Implementar un bloqueo "real" exigiría inyectar un proceso en la sesión del usuario
con `CreateProcessAsUser` a partir de un token duplicado con `WTSQueryUserToken`.
Es un patrón potente y también el patrón exacto de una técnica de movimiento
lateral: eleva mucho el perfil de riesgo del binario ante cualquier EDR.

`WTSDisconnectSession` consigue el efecto observable (sesión bloqueada, hay que
reautenticarse) sin tocar tokens de usuario. Se documenta la diferencia en el
contrato en lugar de disimularla.

### Sin procesos externos

Ni `powershell`, ni `wmic`, ni `netsh` en tiempo de ejecución (`netsh` solo aparece
como reserva durante la instalación). Motivos: superficie de inyección, coste,
disponibilidad en Server Core, y que en hosts endurecidos suelen estar restringidos.

### LocalSystem y el peso del token

Un matiz que conviene explicitar: como el servicio corre como LocalSystem, quien
posea el token tiene, de facto, una credencial de ejecución privilegiada sobre el
host (apagado, y con el updater habilitado, descarga y ejecución de un binario). Ni
TLS sin verificación ni una allowlist vacía reducen ese riesgo por sí solos. Por eso
el instalador **recomienda por defecto** fijar `--allow` con la IP de Home Assistant
en la instalación no silenciosa (ver
[INSTALLER.md](INSTALLER.md#flags-de-install)): es la mitigación de mayor efecto y
coste cero contra el movimiento lateral. La sustitución de LocalSystem por una
cuenta de servicio virtual queda como estudio de la fase 6.

### TLS autofirmado por defecto

Igual que ha4linux. La integración de HA usa `verify_ssl: false` por defecto, lo que
significa que el cifrado protege frente a captura pasiva pero no frente a un
atacante activo en la red local. Para entornos que lo requieran hay dos vías, no
excluyentes: apuntar `tls.certfile`/`keyfile` a un certificado de la PKI interna y
activar la verificación en Home Assistant, o usar el **pinning opcional de la huella
SHA-256** del certificado autofirmado en el alta de la integración (ver
[HA_INTEGRATION.md](HA_INTEGRATION.md#verificación-tls-y-pinning-opcional)). El
pinning autentica el host sin necesidad de PKI y da un uso real a la huella que
imprime `install` y muestra `ha4win.exe cert show`.

## Auditoría

Se registra en el **Event Log** de Windows (origen `HA4Win`), no solo en el fichero:

| Evento | Nivel |
| --- | --- |
| Arranque y parada del servicio, con versión | Information |
| Fallo de validación de configuración | Error |
| TLS desactivado con bind no local | Warning |
| Fallo de autenticación (IP de origen, ruta) | Warning |
| Petición rechazada por `allowed_clients` | Warning |
| Ejecución de cualquier acción de `power_manager` (IP, acción, parámetros) | Information |
| Inicio, resultado y rollback de una actualización | Information / Error |
| Módulo que no se registra y motivo | Information |

Los fallos de autenticación se agregan (máximo una entrada cada 10 s por IP) para
que un escaneo no llene el Event Log.

El fichero `ha4win.log` rota a 10 MB con 5 generaciones. Nunca contiene el token.

## Endurecimiento adicional recomendado

Para el operador, documentado en el README del despliegue:

1. `api.allowed_clients` con la IP de Home Assistant. Es la medida de mayor efecto
   y coste cero.
2. Regla de firewall limitada a esa IP de origen en lugar de al perfil de red.
3. `readonly_mode: true` en servidores donde solo se quiera observar.
4. Certificado de PKI interna y `verify_ssl: true` en la integración.
5. Rotación del token: editar `config.json`, reiniciar el servicio y actualizar la
   entrada en Home Assistant.

## Fuera de alcance

- Scopes por token (`read:sensors`, `write:update`…). Contemplado en el diseño de
  gestión centralizada de ha4linux para la fase 4; ha4win lo adoptará cuando el
  contrato lo defina, para no divergir.
- Autenticación mutua TLS.
- Cifrado del token en reposo: en un host donde el atacante ya es administrador,
  cualquier esquema de cifrado local es reversible por él.
