# HA4Win — Workstation API para Windows

Equivalente de [ha4linux](../ha4linux/) para hosts Windows: un agente local que
expone el sistema como un **dispositivo con entidades** en Home Assistant, con el
mismo contrato API `v1`, el mismo modelo modular de sensores/actuadores y el mismo
mecanismo de actualización remota.

> **Estado: diseño aprobado (2026-08-03), implementación pendiente.**
> Este directorio contiene, por ahora, solo la especificación. El encargo de
> implementación está en [`docs/HANDOFF_CODEX.md`](docs/HANDOFF_CODEX.md).

## Diferencia estructural con ha4linux

`ha4linux` es **dos cosas**: un add-on que corre dentro de Home Assistant y un
cliente instalable en hosts Linux. `ha4win` es **solo cliente**: Home Assistant no
corre sobre Windows, así que no hay add-on, ni `Dockerfile`, ni `config.json` de
supervisor. Esto elimina la mitad del empaquetado y toda la capa `bashio`.

## Decisiones de diseño ya tomadas

| Decisión | Elección | Razón corta |
| --- | --- | --- |
| Lenguaje | **Go** (stdlib + `golang.org/x/sys`) | Binario único estático, cero runtime en el host |
| Empaquetado | **El propio binario se instala** (`ha4win.exe install`) | Ningún instalador ni intérprete adicional; MSI opcional en fase 6 |
| Integración HA | **Nueva** `custom_components/ha4win` | Riesgo cero para la flota ha4linux 0.5.15 en producción |
| Alcance v1 | Núcleo de telemetría + energía/mantenimiento/seguridad | Sesión, mensajería y políticas de apps quedan en roadmap |
| Contrato API | `v1` idéntico a ha4linux + campo `platform` | Una sola familia de contrato, `schema_version` 1.1 |

El razonamiento completo de la elección de Go y del instalador está en
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#1-elección-de-lenguaje).

## Qué expone (v1)

**Sensores**

- `cpu` — uso agregado y por core, procesos/hilos/handles.
- `memory` — física y commit charge.
- `network` — contadores por interfaz y ventanas RX/TX.
- `volumes` — unidades locales, espacio y porcentaje de uso.
- `services` — estado de servicios Windows de una watchlist declarativa.
- `system_info` — edición/build de Windows, uptime, actualizaciones pendientes.
- `maintenance` — reinicio pendiente y motivos, energía y batería.
- `security` — Defender, Firewall y BitLocker (best effort).

**Actuadores**

- `power_manager` — `status`, `lock`, `sleep`, `hibernate`, `restart`, `shutdown`,
  `cancel`. Todo salvo `lock` y `status` requiere habilitación explícita.

**Gestión**

- `/v1/update/*` — actualización remota por manifiesto con `sha256`, swap atómico
  del ejecutable y rollback automático si el health-check falla.

Detalle campo a campo en [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) y
[`docs/MODULES.md`](docs/MODULES.md).

## Índice de documentación

| Documento | Contenido |
| --- | --- |
| [HANDOFF_CODEX.md](docs/HANDOFF_CODEX.md) | Encargo de implementación: orden de lectura, puntos abiertos, reglas y definición de terminado |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Bloques, contrato de módulo, árbol de directorios, decisiones y su porqué |
| [API_CONTRACT.md](docs/API_CONTRACT.md) | Endpoints y payloads exactos, versionado y compatibilidad |
| [MODULES.md](docs/MODULES.md) | Catálogo de módulos: fuente Win32, campos, coste, degradación |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | `config.json` completo, precedencia, validación, permisos |
| [INSTALLER.md](docs/INSTALLER.md) | Subcomandos, instalación, build cruzado, matriz de Windows soportados |
| [UPDATER.md](docs/UPDATER.md) | Manifiesto, preflight, apply/rollback, máquina de estados |
| [SECURITY.md](docs/SECURITY.md) | Modelo de amenaza, privilegios, superficie expuesta, hardening |
| [HA_INTEGRATION.md](docs/HA_INTEGRATION.md) | Integración custom y entidades resultantes |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Fases, criterios de aceptación, matriz de pruebas y riesgos |

## Convivencia con ha4linux

Ambos productos comparten el contrato `v1`, no el código. La convergencia hacia una
integración multiplataforma única (`ha4os`) queda documentada como opción futura en
[`docs/HA_INTEGRATION.md`](docs/HA_INTEGRATION.md#convergencia-futura), sin ninguna
acción requerida ahora sobre la flota Linux existente.
