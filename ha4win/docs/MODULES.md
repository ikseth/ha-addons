# Catálogo de módulos

Para cada módulo: fuente de datos exacta, coste, prerrequisito de alta y
comportamiento cuando la fuente no está disponible.

## Jerarquía de fuentes

Regla de implementación, en orden estricto de preferencia:

1. **API Win32 directa** (`kernel32`, `iphlpapi`, `advapi32`, `powrprof`, `ntdll`).
2. **Registro de Windows**.
3. **COM** (WUA, WMI) — solo donde no hay alternativa.
4. **Proceso externo** — prohibido en el v1. Si algún dato solo se obtuviera así,
   el módulo se declara no disponible con motivo.

El motivo es doble: en hosts securizados WMI y PowerShell pueden estar
restringidos, y en la ruta caliente (`/v1/sensors` cada 20 s) el coste de WMI es
un orden de magnitud mayor que el de una syscall. Por eso **ningún módulo del
núcleo de telemetría usa WMI**.

## Sensores

### `cpu`

| | |
| --- | --- |
| Fuente | `GetSystemTimes` (kernel32) para el agregado; `NtQuerySystemInformation` con `SystemProcessorPerformanceInformation` (ntdll) para el detalle por core; `GetPerformanceInfo` (psapi) para procesos/hilos/handles |
| Coste | < 1 ms |
| Prerrequisito | Ninguno |
| Estado interno | Última muestra de tiempos; el porcentaje es el delta entre lecturas |
| Config | `modules.cpu.enabled` (true), `modules.cpu.per_core` (true) |

En el primer `Collect` tras el arranque no hay muestra previa. Para no devolver un
`0.0` falso, el módulo toma una muestra inicial al registrarse y, si el intervalo
entre lecturas es menor de 1 s, reutiliza el último valor calculado.

`NtQuerySystemInformation` es API semi-documentada. Si la llamada falla, el módulo
sigue publicando el agregado y omite `per_core`, sin marcarse no disponible.

### `memory`

| | |
| --- | --- |
| Fuente | `GlobalMemoryStatusEx` (kernel32) y `GetPerformanceInfo` (psapi) para el commit charge |
| Coste | < 1 ms |
| Prerrequisito | Ninguno |
| Config | `modules.memory.enabled` (true) |

`used_kb = total_kb - available_kb`, igual que en ha4linux, para que el porcentaje
sea comparable entre plataformas.

### `network`

| | |
| --- | --- |
| Fuente | `GetIfTable2` (iphlpapi) |
| Coste | ~1-3 ms según número de interfaces |
| Prerrequisito | Ninguno |
| Estado interno | Contadores por interfaz y timestamp de la última muestra |
| Config | `modules.network.enabled` (true), `include_interfaces`, `exclude_interfaces`, `aggregate_mode` (`selected` \| `all`) |

Se descartan siempre: loopback (`IF_TYPE_SOFTWARE_LOOPBACK`), túneles, y las
interfaces con `oper_status != up` **a efectos de agregado**, aunque siguen
apareciendo en `interfaces` si están seleccionadas explícitamente.

Los filtros por defecto excluyen el ruido típico de Windows:
`exclude_interfaces` por defecto contiene `Loopback*`, `isatap*`, `Teredo*`,
`vEthernet*`, `VirtualBox*`, `VMware*`.

Igual que en ha4linux, si un delta sale negativo (reinicio de NIC o del host) se
usa el contador absoluto como delta de esa ventana, para no publicar valores
negativos ni romper las estadísticas de HA.

### `volumes`

| | |
| --- | --- |
| Fuente | `GetLogicalDriveStringsW` + `GetDriveTypeW` + `GetVolumeInformationW` + `GetDiskFreeSpaceExW` (kernel32) |
| Coste | ~1 ms por unidad local; **una unidad de red caída puede bloquear segundos** |
| Prerrequisito | Ninguno |
| Config | `modules.volumes.enabled` (true), `include_drive_types` (`["fixed"]`), `exclude_mounts` (`[]`) |

`include_drive_types` por defecto solo `fixed`: es la contrapartida directa de
excluir `nfs`/`cifs`/`sshfs` en ha4linux, y evita el modo de fallo más común
—una unidad de red desconectada que congela la enumeración—. Valores admitidos:
`fixed`, `removable`, `network`, `cdrom`, `ramdisk`.

Aunque se incluyan unidades de red, la enumeración va con el plazo del registry:
si tarda más de 3 s el módulo se declara no disponible en esa lectura y se
recupera solo en la siguiente.

`readonly` se deriva del flag `FILE_READ_ONLY_VOLUME` de `GetVolumeInformationW`.

### `services`

| | |
| --- | --- |
| Fuente | `OpenSCManagerW` + `OpenServiceW` + `QueryServiceStatusEx` + `QueryServiceConfigW` (advapi32) |
| Coste | ~0.5 ms por servicio consultado |
| Prerrequisito | Watchlist no vacía. Sin ella el módulo no se registra |
| Config | `modules.services.enabled` (false), `modules.services.watchlist` (`[]`) |

Se consultan **solo** los servicios de la watchlist, nunca se enumera el SCM
completo: en un equipo hay 200-400 servicios y publicarlos todos crearía cientos de
entidades en Home Assistant.

Se acepta tanto el nombre de servicio (`Spooler`) como el nombre visible
(`Print Spooler`); la resolución prueba primero el nombre de servicio. A diferencia
de ha4linux no se añade sufijo alguno al identificador.

`is_failed` tiene definición exacta, porque en Windows no existe el estado
`failed` de systemd:

```
is_failed = estado == STOPPED
            && start_type ∈ {auto, auto_delayed}
            && win32_exit_code ∉ {0, 1077}
```

`1077` es `ERROR_SERVICE_NEVER_STARTED`, el valor normal de un servicio que aún no
ha arrancado en este boot: tratarlo como fallo produciría falsos positivos en cada
reinicio. Un servicio detenido con tipo de arranque manual o deshabilitado **no** es
un fallo: es su configuración.

### `system_info`

| | |
| --- | --- |
| Fuente base | `RtlGetVersion` (ntdll) y registro `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion` (`ProductName`, `DisplayVersion`, `CurrentBuild`, `UBR`, `InstallDate`, `EditionID`); `GetTickCount64` para uptime; `GetComputerNameExW` para dominio |
| Coste base | < 2 ms |
| Fuente de actualizaciones | COM: `Microsoft.Update.Session` → `CreateUpdateSearcher` → `Search("IsInstalled=0 AND IsHidden=0")` |
| Coste de actualizaciones | **segundos a minutos**; nunca en la ruta caliente |
| Config | `modules.system_info.enabled` (true), `updates_enabled` (true), `updates_provider` (`wua` \| `disabled`), `updates_check_interval_sec` (86400), `updates_timeout_sec` (600), `updates_max_packages` (25), `updates_search_scope` (`default` \| `managed`) |

`ProductName` en Windows 11 sigue diciendo "Windows 10" por compatibilidad: se
corrige a "Windows 11" cuando `CurrentBuild >= 22000`.

**Actualizaciones.** Réplica exacta del patrón de ha4linux: refresco en una
goroutine de fondo, caché con TTL de 24 h, `updates_state = "checking"` mientras no
haya una muestra válida, y `Collect` devolviendo siempre la última muestra buena.
`GET /v1/sensors` nunca espera a WUA.

Consideraciones propias de Windows:

- La búsqueda WUA es **online por defecto** y puede tardar minutos o fallar en un
  host aislado. `updates_search_scope: "managed"` fuerza `ServerSelection = ssManagedServer`
  (WSUS/Intune) y evita salir a Internet. En hosts sin conectividad ni WSUS, lo
  correcto es `updates_enabled: false`, y el sensor reporta `updates_state: "disabled"`.
- El servicio `wuauserv` puede estar deshabilitado por política. Se comprueba antes
  de instanciar el COM; si no se puede usar, `updates_state: "unsupported"` con
  motivo, sin reintentos agresivos.
- `updates_reboot_required` se lee de `ISystemInformation.RebootRequired`.

### `maintenance`

| | |
| --- | --- |
| Fuente | Registro para reinicio pendiente; `GetSystemPowerStatus` (kernel32) para energía; `GetTickCount64` para uptime |
| Coste | < 2 ms |
| Prerrequisito | Ninguno |
| Config | `modules.maintenance.enabled` (true) |

Claves consultadas para `pending_reboot`:

| Motivo | Clave |
| --- | --- |
| `component_based_servicing` | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending` |
| `windows_update` | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired` |
| `pending_file_rename` | Valor `PendingFileRenameOperations` en `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager` |
| `computer_rename` | `ComputerName` distinto de `ActiveComputerName` en `HKLM\SYSTEM\CurrentControlSet\Control\ComputerName\*` |
| `sccm` | `HKLM\SOFTWARE\Microsoft\SMS\Mobile Client\Software Distribution\Execution Request State` |

Todo por registro: sin WMI, sin procesos externos, sin coste apreciable.

### `security`

| | |
| --- | --- |
| Fuente Firewall | Registro `HKLM\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\{Domain,Standard,Public}Profile\EnableFirewall` |
| Fuente Defender | WMI `root\Microsoft\Windows\Defender` → `MSFT_MpComputerStatus` |
| Fuente BitLocker | WMI `root\CIMV2\Security\MicrosoftVolumeEncryption` → `Win32_EncryptableVolume` |
| Fuente UAC | Registro `...\Policies\System\EnableLUA` |
| Coste | Firewall y UAC < 1 ms; Defender ~50-200 ms; BitLocker ~100-500 ms por volumen |
| Config | `modules.security.enabled` (true), `defender` (true), `firewall` (true), `bitlocker` (false), `refresh_interval_sec` (300) |

Los dos sub-bloques que usan WMI se refrescan **en segundo plano** con un intervalo
de 5 minutos y se sirven de caché, por la misma razón que las actualizaciones: WMI
no entra en la ruta caliente.

BitLocker viene desactivado por defecto porque es el más caro y el que más varía
entre ediciones de Windows (no existe en Home).

Cada sub-bloque degrada de forma independiente: si Defender fue sustituido por otro
antivirus, la clase WMI no existe y se publica `defender.available: false` con
motivo, sin afectar a firewall ni al resto del sensor.

## Actuadores

### `power_manager`

| Acción | API | Privilegio | Notas |
| --- | --- | --- | --- |
| `status` | `WTSEnumerateSessionsW`, registro | — | Nunca bloqueado por `readonly_mode` |
| `lock` | `WTSDisconnectSession` | — | Sobre la sesión de consola activa. Ver semántica en [API_CONTRACT.md](API_CONTRACT.md#post-v1actuatorspower_manageraction) |
| `sleep` | `SetSuspendState(FALSE, force, FALSE)` (powrprof) | — | |
| `hibernate` | `SetSuspendState(TRUE, force, FALSE)` | — | Solo si la hibernación está habilitada; si no, no aparece en `available_actions` |
| `restart` | `InitiateSystemShutdownExW(..., reboot=TRUE)` | `SE_SHUTDOWN_NAME` | Con cuenta atrás cancelable |
| `shutdown` | `InitiateSystemShutdownExW(..., reboot=FALSE)` | `SE_SHUTDOWN_NAME` | |
| `cancel` | `AbortSystemShutdown` | `SE_SHUTDOWN_NAME` | Cancela la cuenta atrás en curso |

El privilegio `SE_SHUTDOWN_NAME` lo tiene LocalSystem pero está deshabilitado por
defecto en el token: hay que habilitarlo con `AdjustTokenPrivileges` justo antes de
la llamada y volver a deshabilitarlo después.

`allowed_actions` por defecto: `["lock"]`. Todo lo demás requiere habilitación
explícita en configuración, en la misma línea que `poweroff`/`reset` de VirtualBox
en ha4linux. `status` está siempre disponible.

Con `readonly_mode: true` el actuador no se registra en absoluto.

Se registra en el Event Log toda acción que altere el estado del equipo, con la IP
de origen y la acción solicitada.

## Interoperabilidad COM

La necesitan solo `system_info.updates`, `security.defender` y
`security.bitlocker`. Se implementa en `internal/winapi/com` sin dependencias
externas:

- `CoInitializeEx` / `CoUninitialize` por goroutine, con `runtime.LockOSThread`.
- `CoCreateInstance` y llamada a métodos por índice de vtable con
  `syscall.SyscallN`.
- Envoltorios tipados mínimos para `IDispatch` (WUA) e `IWbemServices` (WMI), con
  liberación determinista de `BSTR` y `VARIANT`.

**Es el punto de mayor riesgo técnico del proyecto.** Por eso:

1. Se valida con un *spike* aislado antes de integrarlo (fase 2).
2. Va detrás de una interfaz `updatesProvider` / `wmiProvider`, de modo que el
   valor `disabled` deja el resto del agente intacto.
3. Nunca se ejecuta en la ruta caliente ni sin timeout.

## Roadmap: módulos fuera del v1

| Módulo | Equivalente Linux | Bloqueante |
| --- | --- | --- |
| `session_manager` | `session_manager` | Necesita agente de sesión de usuario para acciones sobre el escritorio |
| `message_dispatcher` | `message_dispatcher` | Toast nativo requiere agente de sesión; `msg.exe` solo cubre el caso trivial |
| `app_policy` | `app_policy` | Requiere decidir el mecanismo de bloqueo (ACL deny vs Image File Execution Options) y su reversibilidad |
| `virtualbox` | `virtualbox` | `VBoxManage.exe` existe en Windows; el bloqueo es la regla de "sin procesos externos" |
| `hyperv` | — | WMI `root\virtualization\v2`; depende de la validación del interop COM |
| `printers`, `eventlog`, `tasks` | — | Ideas específicas de Windows sin equivalente Linux |
