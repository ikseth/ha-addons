# Arquitectura de HA4Win

## 0. Restricción rectora

El agente debe poder instalarse en hosts **mínimos, aislados, antiguos o
securizados**. De ahí se derivan tres reglas duras que atraviesan todo el diseño:

1. **Cero dependencias de runtime en el host.** Nada que instalar antes: ni Python,
   ni .NET, ni Visual C++ Redistributable, ni módulos de PowerShell.
2. **Cero dependencias de red durante la instalación.** El binario que se copia es
   todo lo necesario, incluido el certificado TLS, que se genera localmente.
3. **Degradación explícita, nunca fallo total.** Un módulo que no puede leer su
   fuente en un host endurecido se declara `available: false` con motivo; no tumba
   el resto de la API.

## 1. Elección de lenguaje

Evaluado contra la restricción rectora:

| Candidato | Dependencia en el host | Peso | Veredicto |
| --- | --- | --- | --- |
| Python + PyInstaller | Ninguna tras empaquetar, pero el ejecutable empaquetado desempaqueta en `%TEMP%` en cada arranque y es un patrón habitualmente marcado por AV/EDR | ~45 MB | Descartado: fricción alta justo en los hosts securizados que son el caso difícil |
| .NET Framework 4.x | En caja desde Windows 8, pero versión variable por build; en Server Core y ediciones recortadas no siempre está completo | ~2 MB | Descartado: la dependencia existe aunque suela estar satisfecha |
| .NET 8 self-contained | Ninguna | ~70 MB | Descartado por peso y por el árbol de ficheros que despliega |
| **Go** | **Ninguna** | **~8-12 MB, un solo fichero** | **Elegido** |

Go además encaja con el resto de restricciones del proyecto:

- **Enlazado estático con `CGO_ENABLED=0`**: un `.exe` autocontenido, sin DLLs
  propias, sin manifiesto de dependencias.
- **Servicio Windows nativo** vía `golang.org/x/sys/windows/svc`, sin envoltorios
  tipo NSSM.
- **Servidor HTTP, TLS y generación de certificados X.509 en la biblioteca
  estándar**: `net/http`, `crypto/tls`, `crypto/x509`. No hace falta OpenSSL en el
  host ni en el build.
- **Compilación cruzada desde el equipo de desarrollo Linux** ya existente:
  `GOOS=windows go build`. No se necesita una máquina Windows para producir
  releases.
- **Huella en ejecución baja**: ~15 MB RSS en reposo, adecuado para hosts antiguos.

### Política de dependencias

El `go.mod` puede contener **exactamente un** módulo externo:

```
golang.org/x/sys
```

Cualquier dependencia adicional requiere justificación explícita en el PR. En
particular, **no** se usa `github.com/go-ole/go-ole`: la interoperabilidad COM
mínima que necesitan WUA y WMI se implementa en `internal/winapi/com` sobre
`golang.org/x/sys/windows` (ver [MODULES.md](MODULES.md#interoperabilidad-com)).

### Consecuencia sobre el instalador

Una vez elegido Go, arrastrar Inno Setup o WiX significaría reintroducir un
artefacto de instalación que el propio binario no necesita. El instalador **es el
binario**: `ha4win.exe install`. Se copia un fichero y se ejecuta un subcomando.
Funciona sin PowerShell — relevante porque en hosts securizados es habitual
encontrar Constrained Language Mode o AppLocker bloqueando scripts.

El MSI queda como envoltorio **opcional** de fase 6 para despliegue por GPO/Intune,
y lo único que hace es dejar el `.exe` y llamar a su propio `install`.

## 2. Bloques

```
                    Home Assistant
                          │  HTTPS + Bearer
                          ▼
┌──────────────────────────────────────────────────┐
│  ha4win.exe  (servicio Windows, LocalSystem)     │
│                                                  │
│  api/       enrutado v1, auth, TLS, deadlines    │
│  registry/  alta condicionada de módulos         │
│  sensors/   telemetría        actuators/ acciones│
│  update/    manifiesto, preflight, apply         │
│  state/     estado persistente atómico           │
│  winapi/    envoltorios syscall Win32            │
└──────────────────────────────────────────────────┘
        │                │                  │
   Win32 API        Registro           SCM / WUA / WMI
```

Un host Windows = un `device` en Home Assistant. Cada sensor mapea a entidades de
telemetría; cada acción de actuador a un `button` o `switch`.

## 3. Contrato de módulo

```go
// internal/registry/module.go

type Sensor interface {
    ID() string
    Collect(ctx context.Context) (map[string]any, error)
}

type Actuator interface {
    ID() string
    Describe() map[string]any
    Execute(ctx context.Context, action string, params map[string]any) (map[string]any, error)
}

// Opcional. Si el módulo la implementa, el registry la consulta al arrancar y
// omite el alta cuando devuelve false, registrando el motivo en el log.
type Probe interface {
    Available() (bool, string)
}
```

Es el mismo contrato de ha4linux (`id` + `collect()` / `execute(action, params)`)
con dos adiciones deliberadas:

- **`context.Context`**: permite imponer un plazo por módulo. En Linux la protección
  frente a un módulo lento se resolvió a posteriori con caché en segundo plano
  (`system_info`, `virtualbox`); aquí el plazo es parte del contrato desde el
  principio, porque en Windows hay llamadas (WUA, WMI, BitLocker) que pueden
  bloquear minutos.
- **`Probe`**: formaliza la "exposición condicional" que en ha4linux está repartida
  en comprobaciones ad hoc dentro de `ModuleRegistry.load()`.

## 4. Resiliencia

| Riesgo | Mitigación |
| --- | --- |
| Un sensor bloqueado congela `GET /v1/sensors` | Plazo por módulo (`sensor_timeout_sec`, 3 s por defecto). Al vencer: `available: false`, `reason: "timeout"`. El resto del payload se sirve igual |
| Un sensor entra en pánico | `recover()` por módulo en el registry; se traduce a `available: false` con el motivo |
| Fuente cara (WUA, BitLocker) | Refresco en hilo de fondo + caché con TTL largo. `Collect` devuelve siempre la última muestra válida y el estado `checking` hasta tener una |
| Contadores que se resetean (reinicio de NIC) | Igual que en ha4linux: si el delta sale negativo se usa el valor absoluto como delta de la ventana |
| Fallo tras una actualización | Health-check post-arranque y rollback automático al binario anterior (ver [UPDATER.md](UPDATER.md)) |
| El servicio muere | Acciones de recuperación del SCM: reinicio a los 5 s, 10 s y 60 s |

## 5. Modelo de privilegios

El servicio corre como **LocalSystem**. No existe el equivalente a `sudoers`
porque no hace falta escalar: LocalSystem ya tiene los privilegios necesarios para
todo el alcance v1 (leer contadores, consultar el SCM, apagar, consultar WUA).

La contrapartida es que LocalSystem es una cuenta muy potente, así que la
superficie de acción se acota por configuración, no por permisos del sistema:
`readonly_mode`, `actuators.power.allowed_actions` y el token de API. El análisis
está en [SECURITY.md](SECURITY.md).

**Limitación conocida y aceptada:** el servicio vive en la sesión 0 y no puede
interactuar con el escritorio del usuario. Por eso el v1 no incluye mensajería ni
notificaciones toast: requerirían un agente de sesión de usuario
(`ha4win-agent.exe`), que se diseña en la fase 7 del roadmap y no antes.

## 6. Árbol de directorios

```
ha4win/
├── README.md
├── go.mod                          # module github.com/ikseth/ha-addons/ha4win
├── go.sum
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API_CONTRACT.md
│   ├── MODULES.md
│   ├── CONFIGURATION.md
│   ├── INSTALLER.md
│   ├── UPDATER.md
│   ├── SECURITY.md
│   ├── HA_INTEGRATION.md
│   └── IMPLEMENTATION_PLAN.md
├── cmd/
│   └── ha4win/
│       ├── main.go                 # dispatch de subcomandos
│       ├── cmd_install.go          # install / uninstall
│       ├── cmd_service.go          # punto de entrada SCM
│       ├── cmd_run.go              # ejecución en primer plano (depuración)
│       ├── cmd_config.go           # config print / validate
│       ├── cmd_cert.go             # cert generate / show
│       └── cmd_update.go           # update apply / rollback locales
├── internal/
│   ├── api/
│   │   ├── server.go               # net/http, TLS, apagado ordenado
│   │   ├── routes.go               # tabla de rutas v1
│   │   ├── auth.go                 # Bearer en tiempo constante, allowed_clients
│   │   └── errors.go               # forma canónica de error
│   ├── config/
│   │   ├── config.go               # struct de configuración
│   │   ├── load.go                 # fichero + env + defaults
│   │   ├── defaults.go
│   │   └── validate.go
│   ├── registry/
│   │   ├── module.go               # interfaces Sensor/Actuator/Probe
│   │   └── registry.go             # alta condicionada, deadlines, recover
│   ├── sensors/
│   │   ├── cpu/
│   │   ├── memory/
│   │   ├── network/
│   │   ├── volumes/
│   │   ├── services/
│   │   ├── systeminfo/             # incluye el proveedor de actualizaciones
│   │   ├── maintenance/
│   │   └── security/
│   ├── actuators/
│   │   └── power/
│   ├── update/
│   │   ├── manager.go              # status/check/apply/rollback
│   │   ├── manifest.go             # descarga y parseo, canales
│   │   ├── preflight.go            # requisitos verificables antes de aplicar
│   │   └── applier.go              # swap atómico, health-check, rollback
│   ├── state/
│   │   └── state.go                # JSON atómico en ProgramData
│   ├── logging/
│   │   └── logging.go              # fichero rotado + Event Log
│   ├── setup/
│   │   ├── install.go              # directorios, ACL, config, servicio
│   │   ├── acl.go                  # SDDL sobre ProgramData\HA4Win
│   │   ├── firewall.go             # regla de entrada
│   │   ├── cert.go                 # autofirmado con crypto/x509
│   │   └── eventlog.go             # alta del origen de Event Log
│   ├── winapi/
│   │   ├── kernel32.go             # GetSystemTimes, GlobalMemoryStatusEx, discos
│   │   ├── iphlpapi.go             # GetIfTable2
│   │   ├── advapi32.go             # SCM, privilegios, apagado
│   │   ├── powrprof.go             # SetSuspendState
│   │   ├── wtsapi32.go             # enumeración y desconexión de sesiones
│   │   ├── ntdll.go                # SystemProcessorPerformanceInformation
│   │   ├── registry.go             # lecturas tipadas del registro
│   │   └── com/                    # interop COM mínima (WUA, WMI)
│   └── version/
│       └── version.go              # constantes inyectadas por ldflags
├── build/
│   ├── build.sh                    # matriz de compilación cruzada
│   ├── build-update-asset.sh       # zip del artefacto + sha256
│   └── render-update-manifest.sh   # manifiesto de canal
├── update-assets/                  # artefactos publicados (igual que ha4linux)
├── update-manifest.json
└── branding/
    ├── ha4win-icon.svg
    ├── icon.png
    └── logo.png
```

Y, fuera de este directorio, en la raíz del repositorio:

```
custom_components/ha4win/           # integración de Home Assistant (ver HA_INTEGRATION.md)
```

### Correspondencia con ha4linux

| ha4linux | ha4win | Nota |
| --- | --- | --- |
| `app/core/config.py` | `internal/config/` | Misma precedencia env > fichero > defaults |
| `app/core/registry.py` | `internal/registry/` | Añade deadlines y `Probe` |
| `app/core/runtime_state.py` | `internal/state/` | Sin historial de mensajes en v1 |
| `app/core/update_manager.py` | `internal/update/manager.go` | Mismo contrato de manifiesto |
| `app/core/update_preflight.py` | `internal/update/preflight.go` | Comprobaciones propias de Windows |
| `packaging/common/install-client.sh` | `internal/setup/` + `cmd_install.go` | Instalador embebido en el binario |
| `packaging/assets/*update*` | `internal/update/applier.go` | Sin helpers externos: el binario se actualiza a sí mismo |
| `tray/ha4linux-tray` | — | Fuera del alcance v1 |
| `Dockerfile`, `run.sh`, `config.json` | — | No hay add-on de HA para Windows |

## 7. Nombres y rutas fijas

| Concepto | Valor |
| --- | --- |
| Nombre de servicio | `ha4win` |
| Nombre visible | `HA4Win Workstation API` |
| Instalación | `C:\Program Files\HA4Win\ha4win.exe` |
| Configuración | `C:\ProgramData\HA4Win\config.json` |
| Estado | `C:\ProgramData\HA4Win\state\` |
| Certificados | `C:\ProgramData\HA4Win\certs\` |
| Logs | `C:\ProgramData\HA4Win\logs\ha4win.log` + Event Log `HA4Win` |
| Staging de update | `C:\ProgramData\HA4Win\update\` |
| Puerto por defecto | `8099/tcp` (igual que ha4linux; un host es Linux o Windows, nunca los dos) |

## 8. Principios heredados de ha4linux

- Módulos habilitables/deshabilitables por configuración.
- Exposición condicional: solo se registra lo que tiene sus prerrequisitos.
- Fallos aislados: un módulo caído no derriba el core.
- Superficie de acción mínima por defecto.
- Todo lo destructivo es opt-in explícito.
