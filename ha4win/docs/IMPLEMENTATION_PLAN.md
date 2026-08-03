# Plan de implementación

Documento de encargo para Codex. Cada fase es un incremento entregable, con
criterios de aceptación verificables. **Una fase no se da por cerrada sin cumplir
sus criterios**, de acuerdo con la directriz del repositorio de no hacer commits
sin validación funcional.

## Reglas transversales

Aplican a todas las fases y no se repiten en cada una:

1. `go.mod` no admite más dependencia externa que `golang.org/x/sys`. Cualquier
   otra requiere justificación explícita.
2. Ningún módulo ejecuta procesos externos en tiempo de ejecución.
3. Ningún módulo bloquea `GET /v1/sensors`: lo caro va a hilo de fondo con caché.
4. Todo módulo nuevo se registra condicionalmente y degrada con motivo.
5. Todo error devuelto al cliente lleva `ok: false` y un `error` legible; nunca un
   *stack trace*.
6. `go vet` y `gofmt` limpios. Tests con `go test ./...`.
7. Los tests de lógica pura (parseo, filtros, deltas, semver, validación de
   configuración) **corren en Linux**; el código dependiente de Win32 se aísla tras
   interfaces para poder testear la lógica sin Windows.

## Fase 0 — Esqueleto y ciclo de vida

**Entregable**: un servicio instalable que responde por TLS.

- `cmd/ha4win` con el despacho de subcomandos.
- `internal/config`: carga fichero + entorno + defaults, validación, `config print`
  y `config validate`.
- `internal/logging`: fichero rotado + Event Log.
- `internal/setup`: directorios, DACL, certificado autofirmado, alta del servicio,
  regla de firewall, Event Log; y su reverso en `uninstall`.
- `internal/api`: servidor `net/http` con TLS, auth Bearer en tiempo constante,
  `allowed_clients`, límites de cuerpo y timeouts.
- Endpoints `GET /health` y `GET /v1/version`.
- `internal/version` con valores inyectados por `ldflags`.
- `build/build.sh` con la matriz `amd64`/`arm64`/`386`.

**Aceptación**

- `ha4win.exe install --port 8099` en un Windows limpio deja el servicio corriendo
  y arranca solo tras reiniciar el equipo.
- `curl -k https://<host>:8099/health` responde `{"status":"ok"}`.
- `/v1/version` sin token devuelve 401; con token correcto devuelve el payload
  completo incluido `platform: "windows"`.
- Un usuario estándar **no** puede leer `C:\ProgramData\HA4Win\config.json`.
- `uninstall` deja el sistema sin servicio, sin regla de firewall y sin origen de
  Event Log.
- El binario es un único fichero de menos de 15 MB y no requiere nada preinstalado.

## Fase 1 — Núcleo de telemetría

**Entregable**: `GET /v1/sensors` con `cpu`, `memory`, `network`, `volumes`,
`services` y `system_info` sin el bloque de actualizaciones.

- `internal/registry` con el contrato de módulo, alta condicionada, plazo por
  módulo y `recover` por módulo.
- `internal/winapi`: `kernel32`, `iphlpapi`, `advapi32`, `ntdll`, `registry`.
- Los seis sensores según [MODULES.md](MODULES.md).
- `GET /v1/capabilities`.

**Aceptación**

- El payload coincide campo a campo con [API_CONTRACT.md](API_CONTRACT.md).
- `GET /v1/sensors` responde en menos de 100 ms con todos los módulos activos.
- Un sensor que devuelve error o excede el plazo aparece como
  `available: false` con motivo y **el resto del payload se sirve igual**.
- Los porcentajes de CPU y las ventanas de red son coherentes en lecturas
  consecutivas a 20 s y no aparecen negativos tras deshabilitar y rehabilitar una
  NIC.
- Con `include_drive_types: ["fixed"]`, una unidad de red desconectada no aparece
  ni retrasa la respuesta.
- Un servicio de la watchlist que no existe no rompe el módulo.
- Tests unitarios en Linux de: filtrado de interfaces por comodín, cálculo de
  deltas con reset de contador, normalización de la watchlist, resolución de
  configuración con precedencia entorno > fichero > defaults.

## Fase 2 — Actualizaciones del sistema, mantenimiento y seguridad

**Entregable**: `system_info` completo, `maintenance` y `security`.

**Antes de integrar nada**: *spike* aislado de interoperabilidad COM que valide, en
un Windows real, una búsqueda WUA y una consulta WMI a `MSFT_MpComputerStatus`
usando solo `golang.org/x/sys/windows`. Si el spike no sale limpio, se decide ahí
—no después— si se acepta una dependencia externa acotada. **Este es el mayor
riesgo técnico del proyecto y se ataca primero.**

- `internal/winapi/com` con la interop mínima.
- Proveedor de actualizaciones tras interfaz, con valor `disabled`.
- Refresco en segundo plano con caché de 24 h para actualizaciones y de 5 min para
  Defender/BitLocker.
- `maintenance` completo por registro.

**Aceptación**

- `GET /v1/sensors` sigue por debajo de 100 ms con las actualizaciones activas.
- Tras un arranque en frío, `updates_state` es `checking` y pasa a `idle` con el
  recuento correcto sin que ninguna petición se haya bloqueado.
- Con `updates_enabled: false`, ningún objeto COM llega a instanciarse.
- Con `wuauserv` deshabilitado, `updates_state` es `unsupported` con motivo y sin
  reintentos en bucle.
- En un host sin Defender, `security.defender.available` es `false` y el resto del
  sensor sigue publicándose.
- `pending_reboot` se pone a `true` tras instalar una actualización pendiente de
  reinicio y vuelve a `false` tras reiniciar.
- Sin fugas de memoria tras 24 h: los `BSTR`, `VARIANT` e interfaces COM se liberan.

## Fase 3 — Actuador de energía

**Entregable**: `power_manager` completo y `POST /v1/actuators/{id}/{action}`.

- Allowlist de acciones, `available_actions` calculadas, `readonly_mode`.
- Habilitación y retirada de `SE_SHUTDOWN_NAME` alrededor de la llamada.
- Registro en Event Log de cada acción con IP de origen.

**Aceptación**

- Con la configuración por defecto, solo `status` y `lock` están disponibles;
  `shutdown` devuelve `ok: false` con "not allowed" y **no apaga nada**.
- Con `allowed_actions: ["lock","restart","shutdown"]`, `restart` con
  `delay_seconds: 60` programa el reinicio, `cancel` lo aborta y el equipo no se
  reinicia.
- `lock` desconecta la sesión de consola activa; sin sesión activa devuelve
  `ok: true` con mensaje, no error.
- `hibernate` no aparece en `available_actions` en un equipo con hibernación
  deshabilitada.
- Con `readonly_mode: true`, `capabilities.actuators` está vacío.
- Cada acción ejecutada deja su entrada en el Event Log.

## Fase 4 — Actualización remota

**Entregable**: `/v1/update/*` completo con swap atómico y rollback.

- `internal/update`: manifiesto con canales, preflight, aplicador.
- `update-state.json` persistente para reportar el desenlace tras el reinicio.
- `build/build-update-asset.sh` y `build/render-update-manifest.sh`.

**Aceptación**

- `apply` de 0.1.0 → 0.2.0 en un host real: el servicio vuelve a estar arriba en
  menos de 60 s y `/v1/version` reporta la versión nueva.
- Un artefacto con `sha256` incorrecto se rechaza **antes** de tocar la instalación.
- Un artefacto que no arranca provoca rollback automático y el host queda en 0.1.0
  con el servicio operativo. Este caso se prueba a propósito con un binario
  saboteado.
- `rollback` desde 0.2.0 devuelve a 0.1.0.
- Tras el reinicio, `/v1/update/status` refleja `last_applied_at` y, si lo hubo, el
  error del intento anterior.
- Con `enabled: false`, `supports_apply` es `false` y `apply` no hace nada.
- Dos `apply` concurrentes: el segundo se rechaza sin corromper la instalación.

## Fase 5 — Integración de Home Assistant

**Entregable**: `custom_components/ha4win` funcional.

- Estructura y entidades según [HA_INTEGRATION.md](HA_INTEGRATION.md).
- `config_flow` con rechazo de hosts no Windows.
- Servicio `ha4win.power_action`.
- Entidades `update` del agente y de la propia integración.
- `strings.json` y `translations/es.json`.
- Nivel de repositorio: añadir `custom_components/ha4win` y `ha4win/` al
  `README.md` raíz, y revisar `hacs.json` —hoy declara `"name": "HA4Linux"`, que
  con dos integraciones en el repositorio pasa a ser engañoso—.

**Aceptación**

- Alta desde la UI con host, puerto, token y HTTPS; el dispositivo aparece con
  nombre, modelo y `sw_version` correctos.
- Se crean las entidades de los módulos disponibles y **ninguna** de los ausentes.
- CPU, memoria, red y volúmenes generan estadísticas de largo plazo sin avisos de
  `state_class` en el log de Home Assistant.
- Los botones aparecen solo para las acciones permitidas por el host, y cambiar la
  configuración del host y recargar la entrada los ajusta.
- Apuntar la integración a un host ha4linux se rechaza con mensaje claro.
- La entidad `update` detecta una versión nueva publicada y la instala.
- Sin errores ni avisos en el log de HA durante 24 h de funcionamiento.

## Fase 6 — Endurecimiento y distribución

- `api.allowed_clients` verificado con IPv6.
- `require_signed_asset` con `WinVerifyTrust`.
- Firma Authenticode en el pipeline de build (`osslsigncode`).
- Build legacy con Go 1.20.14 para Windows 7/8.1/Server 2012 R2.
- Evaluación de cuenta de servicio virtual `NT SERVICE\ha4win` en sustitución de
  LocalSystem, condicionada a que WUA y el SCM sigan funcionando.
- MSI opcional con WiX v5 para GPO/Intune.

## Fase 7 — Roadmap (fuera del encargo actual)

Agente de sesión de usuario `ha4win-agent.exe` y, sobre él, `session_manager`,
`message_dispatcher` con toast nativo y `app_policy`. Requiere su propio ciclo de
diseño: IPC servicio↔agente, arranque por sesión, y modelo de bloqueo de
aplicaciones reversible.

## Matriz de validación

| Escenario | Fase | Cómo |
| --- | --- | --- |
| VM cliente Windows moderno (WIN1104) | 0-5 | Host de referencia. VM de pruebas dedicada; encendida puntualmente |
| VM cliente **sin sesión logada** (solo sesión 0) | 3 | Sustituye al servidor: valida `lock` y energía sin consola interactiva |
| Windows Server 2016+ | — | **No disponible en el entorno.** Soporte enviado por diseño, sin validar en servidor moderno real |
| Windows 10 sin conectividad | 2 | `updates_enabled: false`, sin COM |
| Host con antivirus de terceros | 2 | `defender.available: false` |
| Windows 8.1 | 6 | Build legacy, best effort |
| Reinicio del host durante `apply` | 4 | Estado consistente al volver |
| Pérdida de red entre HA y el host | 5 | Entidades a `unavailable`, recuperación sola |

## Riesgos

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| Interop COM en Go puro más complejo de lo previsto | Alto | Spike primero en fase 2; proveedor tras interfaz con valor `disabled`; decisión explícita sobre dependencia si falla |
| Falsos positivos de antivirus sobre el binario | Medio | Sin empaquetador, sin `CreateProcessAsUser`, firma Authenticode opcional |
| `NtQuerySystemInformation` es API semi-documentada | Bajo | Solo alimenta `per_core`; su fallo no degrada el módulo |
| Enumeración de volúmenes bloqueada por unidad de red | Medio | `include_drive_types: ["fixed"]` por defecto y plazo por módulo |
| Búsqueda WUA lenta o colgada en host aislado | Medio | Hilo de fondo, timeout de 600 s, caché de 24 h, `updates_search_scope: managed` |
| Divergencia de contrato con ha4linux | Medio | `schema_version` compartido; simetría de nombres documentada en API_CONTRACT.md |
| Duplicación de la capa de entidades entre las dos integraciones | Bajo | Aceptada conscientemente; ruta de convergencia documentada |

## Prerrequisito operativo

Entorno de pruebas resuelto; el detalle operativo (ruta de acceso en dos saltos,
inventario, despliegue por SMB+RPC, política de uso de los candidatos y HA de
pruebas) está en [`HANDOFF_CODEX.md`](HANDOFF_CODEX.md#5-entorno-de-pruebas).

Resumen: banco principal en `WIN1104`, VM VMware de pruebas dedicada (apagada, se
enciende puntualmente), HA de pruebas en la misma VLAN (`192.168.45.60`),
despliegue del binario por MSRPC/SCM desde `nodo01`. No hay
Windows Server moderno: su soporte se envía por diseño sin validación en servidor
real (ver limitación aceptada en el handoff).
