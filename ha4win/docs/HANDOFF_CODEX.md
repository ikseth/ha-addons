# Traspaso a implementación

**Para**: Codex, como implementador de ha4win.
**De**: fase de diseño.
**Estado**: diseño **aprobado** por el propietario del repositorio el 2026-08-03.
**Encargo**: implementar las fases 0 a 5 de
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## 1. Verificación previa

**Esta verificación ya se hizo una vez** (Codex, 2026-08-03) y su resultado se
incorporó al diseño: ver la sección 3bis, "Resolución de la verificación de gaps".
Puedes hacer una segunda pasada de contraste, pero el grueso de gaps y colisiones ya
está resuelto en los documentos. Céntrate en confirmar que las resoluciones son
coherentes y en cualquier hueco nuevo.

Las decisiones de diseño ya están todas cerradas (sección 4). Lo que sigue abierto
es del entorno, no del diseño (sección 5).

Lo que se espera de esa revisión:

- **Gap**: algo que el diseño da por supuesto y no especifica lo suficiente para
  implementarlo sin inventar.
- **Colisión**: dos documentos que dicen cosas incompatibles, o algo que choca con
  lo que ya existe en el repositorio (`ha4linux/`, `custom_components/`).
- **Duda**: una decisión de diseño que crees equivocada o cara de sostener. Dilo
  ahora, no a mitad de la fase 3.

La sección 3 lista las colisiones que ya se detectaron y corrigieron: no hace falta
volver a levantarlas, pero sí verificar que la corrección es coherente.

## 2. Orden de lectura

| # | Documento | Para qué |
| --- | --- | --- |
| 1 | [`../README.md`](../README.md) | Qué es y decisiones tomadas |
| 2 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | Restricción rectora, elección de Go, contrato de módulo, árbol de directorios |
| 3 | [`API_CONTRACT.md`](API_CONTRACT.md) | **La especificación normativa.** Payloads campo a campo |
| 4 | [`MODULES.md`](MODULES.md) | Fuente Win32 exacta de cada dato y su degradación |
| 5 | [`CONFIGURATION.md`](CONFIGURATION.md) | `config.json`, precedencia, validación, permisos |
| 6 | [`INSTALLER.md`](INSTALLER.md) | Subcomandos, secuencia de instalación, build cruzado |
| 7 | [`UPDATER.md`](UPDATER.md) | Manifiesto, preflight, swap atómico, rollback |
| 8 | [`SECURITY.md`](SECURITY.md) | Modelo de amenaza y decisiones deliberadas |
| 9 | [`HA_INTEGRATION.md`](HA_INTEGRATION.md) | Integración custom y entidades |
| 10 | [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Fases y criterios de aceptación |

Contexto imprescindible fuera de este directorio:

- [`../../AGENT_CONTEXT.md`](../../AGENT_CONTEXT.md) — directrices operativas del
  repositorio. Prevalecen sobre cualquier cosa de aquí.
- `../../ha4linux/` — el producto hermano. Es la referencia de estilo, de contrato
  y de qué patrones ya se demostraron en producción. **No se toca.**

## 3. Colisiones ya detectadas y resueltas

| Colisión | Resolución |
| --- | --- |
| `build.sh` inyectaba en `main.version` pero el árbol declara `internal/version` | Los `ldflags` apuntan a `${MODULE}/internal/version.{Version,Commit,BuildDate}` |
| `CONFIGURATION.md` mencionaba `ha4win.exe restart`, ausente de la lista de subcomandos | Añadidos `start`, `stop` y `restart` |
| La regla de firewall usaba COM (`INetFwPolicy2`) en fase 0, pero el interop COM no se valida hasta la fase 2 | Fase 0 usa `netsh advfirewall` con argumentos fijos, solo en instalación. COM queda como mejora opcional de fase 6 |
| `services.is_failed` no tenía definición precisa (Windows no tiene el `failed` de systemd) | Definición exacta en [`MODULES.md`](MODULES.md#services), excluyendo `ERROR_SERVICE_NEVER_STARTED` |
| `POST /v1/update/apply` con `target_version` estaba en el contrato pero no en el updater | Documentado, con downgrade prohibido |
| Versionado de agente e integración sin política | Van en paralelo, como ha4linux. Ambos arrancan en `0.1.0` |

## 3bis. Resolución de la verificación de gaps (Codex, 2026-08-03)

La primera pasada de verificación produjo un informe de gaps, colisiones y dudas.
Todo lo accionable se resolvió en los documentos. Resumen de lo cerrado:

**Bloqueantes documentales (resueltos):**

| Tema | Dónde quedó | Resolución |
| --- | --- | --- |
| Reinstalar un `.exe` en uso | [INSTALLER.md](INSTALLER.md#secuencia-de-instalación), paso 5 | Instalación transaccional: temporal → parada → rename → arranque → health-check → rollback |
| Contrato exacto del ciclo de vida SCM | [INSTALLER.md](INSTALLER.md#ciclo-de-vida-del-servicio-contrato-scm) | `BinaryPathName`, checkpoints, plazos, controles Stop/Shutdown, códigos de salida |
| Precedencia de `--config` | [CONFIGURATION.md](CONFIGURATION.md#ubicación-y-precedencia) | `--config` > `HA4WIN_CONFIG_FILE` > default; ruta no estándar se registra en el servicio |

**Colisiones corregidas:** "sin procesos externos" vs `sc.exe` en el updater → ahora
API SCM ([UPDATER.md](UPDATER.md)); "swap atómico" reescrito a copia-a-temporal +
`MoveFileExW`; health-check al bind efectivo, no a `127.0.0.1` ciego; `is_failed`
con fórmula normativa única en MODULES; `power_manager` `status`/readonly coherente;
fallback COM sin margen para dependencias externas; versionado paralelo absoluto;
contrato redefinido como extensión compatible del v1, no idéntico.

**Gaps importantes cerrados:** forma de error HTTP uniforme (incluido middleware),
`400/405/503`; semántica de `allowed_clients` (IP del peer, sin cabeceras forwarded,
IPv4/IPv6 desde Fase 0, evaluada antes que el token); concurrencia con `503`;
defaults de build; merge recursivo de config con tipos inválidos fatales; perfil
X.509 normativo del certificado.

**Dudas aplicadas:** `unique_id` = `host:port` (como ha4linux); llamadas del
coordinator en paralelo con degradación aislada; reconciliación idempotente de
entidades; pinning opcional de huella TLS; allowlist a la IP de HA recomendada en el
instalador; Fase 0 validada solo en amd64 (arm64/386 compile-check); pin de `x/sys`
para el build legacy.

**Decisiones de criterio tomadas con el propietario:** flags de configuración solo
en primera instalación (`--reconfigure` para reescribir); `unique_id` = `host:port`;
`cancel` disponible automáticamente si `restart`/`shutdown` lo están.

## 4. Decisiones cerradas

Los nueve puntos que quedaban abiertos se resolvieron con el propietario el
2026-08-03. **Son vinculantes; no hay que volver a plantearlas.**

| # | Punto | Decisión |
| --- | --- | --- |
| 1 | Host Windows de pruebas | Resuelto. Inventario y candidatos en la sección 5 |
| 2 | Salida del spike COM | Primero Go puro. Si no sale limpio: `updates_provider: disabled` y `security` reducido a firewall+UAC por registro. **Nunca** una dependencia externa nueva |
| 3 | Rama de trabajo | Rama `ha4win` desde `main`. `amcrest-smd` es de otro desarrollo y no se toca |
| 4 | Versión de Go | Estable actual en la rama principal; `1.20.14` solo para el build legacy de fase 6 |
| 5 | Nombre del módulo Go | `github.com/ikseth/ha-addons/ha4win`, con `go.mod` dentro de `ha4win/` |
| 6 | Puerto | Se mantiene `8099`. No pueden colisionar: un host es Linux o Windows |
| 7 | Idioma del código | **Inglés** en identificadores, comentarios, mensajes de log y de error. Documentación en español |
| 8 | Primer valor de `cpu` | Muestra inicial al registrar el módulo; reutilizar el último valor si el intervalo es menor de 1 s; `0` si no hay ninguna muestra previa |
| 9 | `hacs.json` | Renombrado a `ikseth HA-Addons`. Nombre único para todo el repositorio, no uno por integración |

## 5. Entorno de pruebas

### Ruta de acceso

No hay ruta directa desde el equipo de desarrollo. El acceso es en dos saltos:

```
equipo de desarrollo → root@192.168.50.40 (eva-02) → root@192.168.45.9 (nodo01) → VLAN 45
```

`nodo01` está en `vlan45` y tiene `nmap` y la suite Samba (`smbclient`,
`rpcclient`, `net`). Los hosts Windows viven en `192.168.45.0/24`, dominio
`ras.local`.

### Home Assistant de pruebas

`192.168.45.60` — instancia de Home Assistant ("vigilante"), VM VirtualBox,
activa. **Está dentro de la VLAN 45**, la misma que los hosts Windows: la
conectividad HA→agente por el puerto 8099 (fase 5) es intra-subred, sin
enrutado ni cortafuegos de por medio. Es el HA contra el que se valida la
integración.

### Inventario (escaneado el 2026-08-03)

Gestión del hipervisor: **ESXi en `192.168.45.50`**, accesible por **clave SSH
desde `nodo01`** (sin contraseña, ya configurado). Consultable con `vim-cmd` y
`esxcli`. Es la vía para encender/apagar WIN1104 y ajustar sus recursos. El host
tiene 4 cores × 3504 MHz y 32 GB; con las 3 VM de usuario en marcha está al ~70 %
de RAM y ~61 % de CPU.

| IP | Nombre | Tipo | Sistema | Valoración |
| --- | --- | --- | --- | --- |
| *(al encender)* | **WIN1104** (vmid 11) | **VM VMware, apagada** | Windows 10 64-bit, 2 vCPU / 4 GB | **Banco principal.** VM de pruebas dedicada, no productiva. Enciende sin cambios; recorte a 1 vCPU/2 GB recomendado para descargar el host |
| .181 | *(sin nombre publicado)* | VM VMware | Windows moderno, SMBv1 desactivado | Reserva productiva (solo fuera de horario) |
| .182 | WIN1102 | VM VMware | Windows moderno, SMBv1 desactivado | Reserva productiva (solo fuera de horario) |
| .183 | WIN1103 | VM VMware | Windows moderno, SMBv1 desactivado | Reserva productiva (solo fuera de horario) |
| .30 | APP08-SRV | VM VirtualBox | Windows Server 2008 R2 SP1 | Solo validación del build legacy (fase 6) |
| .102 | PLOTER | Físico (Dell) | Windows 7 Pro SP1 | Producción. No tocar |
| .101 | Pc-Iñaky | Físico | Windows moderno | Producción. No tocar |
| .104 | PC-SERGIO | Físico | Windows moderno | Producción. No tocar |
| .185 | Pc-Gustavo | Físico | Windows moderno | Producción. No tocar |
| .107, .110, .115, .200 | DESKTOP-* | Físicos | Windows moderno | Producción. No tocar |
| .186, .187 | *(sin nombre)* | Físicos | Windows moderno | Producción. No tocar |
| .20, .21 | RAS-NAS01 | NAS | Samba 4.15.13 | No es Windows |
| .22 | \_\_SAMBA\_\_ | — | Samba | No es Windows |
| .108, .175 | LANTEK, — | — | Sin identificar | Descartados |

### Política de uso de los candidatos

**Banco principal: `WIN1104`.** VM VMware creada expresamente como máquina de
pruebas, hoy apagada para descargar el servidor. Es el candidato preferente
justamente porque **no es productiva**: evita la restricción de horario que sí
afecta al resto. Estado confirmado sobre el ESXi el 2026-08-03:

- Windows 10 64-bit, **2 vCPU / 4 GB**, apagada. Enciende **sin cambios**: sus
  4 GB entran en los ~9.6 GB libres del host (quedaría al ~82 % de RAM).
- **Recorte recomendado a 1 vCPU / 2 GB** para descargar el host (lo dejaría al
  ~76 %). Un Windows 10 con el agente (~15 MB RSS) va sobrado con eso. Es una
  edición del `.vmx` con la VM apagada, reversible.
- Se enciende puntualmente para las tandas de prueba y se apaga al terminar
  (`vim-cmd vmsvc/power.on 11` / `power.off` sobre el ESXi `.50` por clave SSH).
- **Snapshot antes** de las fases destructivas (fase 3 `shutdown`/`restart`;
  fase 4 sabotaje del binario para forzar rollback) y restauración después.
- **IP en la VLAN 45: `192.168.45.184`** (confirmada el 2026-08-03; es DHCP, puede
  cambiar entre arranques — comprobar con `vim-cmd vmsvc/get.guest 11`).

**Reservas (`WIN1102` / `WIN1103` / `.181`)**: puestos productivos de tres
usuarios. Solo si `WIN1104` no estuviera disponible, y entonces **solo fuera de
horario, sin sesión de usuario activa y con snapshot previo**.

Algunos PC físicos son terminales de bajo uso y podrían liberarse como banco
alternativo, pendiente de confirmación in situ del propietario. Hasta esa
confirmación, **ningún host físico se toca**: son puestos en producción y la
fase 3 los apagaría.

### Despliegue remoto (bucle de pruebas) — verificado 2026-08-03

No hay WinRM ni SSH en los hosts. El canal es **SMB + Service Control Manager sobre
MSRPC** (445/135 abiertos), estilo PsExec, con la **suite Samba `net`/`smbclient`
que ya está en `nodo01` y en `eva-02`**. Autenticación **NTLM**, con el formato
inline `-U "RAS/<usuario>%<clave>"`. **No hace falta Kerberos ni instalar nada**
(se comprobó que NTLM funciona y que la cuenta de dominio usada es admin local en
WIN1104: `C$` y `ADMIN$` accesibles).

Flujo:

1. Subir el binario: `smbclient //192.168.45.184/C$ -U "RAS/<usuario>%<clave>" -c 'put ha4win.exe Windows\Temp\ha4win.exe'`.
2. Ejecutar **una sola vez** el instalador embebido. Con la suite Samba se hace con
   `net rpc service create/start` apuntando a un lanzador que invoque
   `ha4win.exe install --quiet --token=…`; el propio `install` registra el servicio
   definitivo, genera el certificado, aplica el DACL y arranca.
3. A partir de ahí es un servicio normal; las actualizaciones van por `/v1/update`.

Notas operativas y de seguridad:

- **`eva-02` tiene ruta directa a la VLAN 45** (vía `192.168.50.10`) y un `smbclient`
  moderno (4.23), así que puede desplegar sin pasar por `nodo01`.
- **La ruta `smbclient -A <authfile>` daba `NT_STATUS_LOGON_FAILURE`** con estas
  mismas credenciales por una peculiaridad de esa vía; usar `-U "DOM/user%pass"`
  inline, que es lo que funciona y lo que usó el despliegue anterior.
- El `-U ...%clave` deja la contraseña en la línea de comando (visible en `ps` del
  host que lanza). Aceptable en la infraestructura propia; para no filtrarla a logs
  o transcripciones, construir la cadena `-U` a partir de un fichero de credenciales
  `600` (`/tmp/ha4win.auth` en los saltos) en lugar de teclearla.
- **Higiene**: los logs de sesiones de Codex (`~/.codex/sessions`) contienen
  credenciales de dominio en claro de despliegues anteriores; el propietario ya rotó
  la contraseña. Conviene no reutilizar credenciales que hayan quedado en logs.

### Limitación aceptada: sin Windows Server moderno

No hay ni habrá a corto/medio plazo un Windows Server superior al 2008 R2. En
consecuencia:

- El soporte de Windows Server moderno (2016+) se **envía por diseño** —usa el
  mismo SCM y las mismas APIs Win32 que el cliente— pero **no se valida en
  hardware de servidor moderno real**. Se documenta como *best effort*, igual que
  el build legacy, por falta de banco de pruebas, no por falta de soporte.
- El caso "sin sesión de consola interactiva" de la matriz se cubre en una VM
  cliente **sin ningún usuario logado** (solo sesión 0), que ejercita la misma
  ruta de código relevante para `lock` y para las acciones de energía.
- `APP08-SRV` (2008 R2) cubre la validación del build legacy de la fase 6.

### Pendiente de confirmar al tomar posesión del host

Versión y edición exactas de las VM candidatas: no se leen en remoto porque
tienen SMBv1 desactivado —que es lo correcto—. Se confirman en la primera sesión.

## 6. Reglas de trabajo

De [`AGENT_CONTEXT.md`](../../AGENT_CONTEXT.md), sin reinterpretar:

1. Nada de soluciones ad hoc rápidas.
2. Escalabilidad, resiliencia y modularidad por delante de la solución rápida.
3. Decisiones estratégicas y mantenibles, no tácticas, salvo justificación técnica
   fuerte y explícita.
4. **Commits solo tras validar funcionalmente los cambios.**
5. Proponer el plan antes de aplicar cambios, para validación previa del usuario.
6. Los puntos críticos inferidos se plantean explícitamente, no se resuelven en
   silencio.

Específicas de este proyecto, de
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md#reglas-transversales):

7. `go.mod` no admite más dependencia externa que `golang.org/x/sys`.
8. Ningún módulo ejecuta procesos externos **en tiempo de ejecución**. La única
   excepción, documentada, es `netsh` durante la instalación.
9. Nada bloquea `GET /v1/sensors`: lo caro va a hilo de fondo con caché.
10. Todo módulo se registra condicionalmente y degrada con motivo.
11. `gofmt` y `go vet` limpios; la lógica pura se testea sin Windows.

## 7. Qué no hay que tocar

- `ha4linux/` y `custom_components/ha4linux/` — están en producción sobre una flota
  real. Sirven de referencia, no de material de refactor.
- `custom_components/amcrest_smd/` — ajeno a este trabajo.
- `AGENT_CONTEXT.md` tiene modificaciones sin commitear de antes de este encargo;
  no las incluyas en tus commits.

## 8. Definición de terminado

Una fase está cerrada cuando:

1. Cumple **todos** sus criterios de aceptación, verificados sobre un host Windows
   real, no razonados sobre el código.
2. `go build` de la matriz completa (`amd64`, `arm64`, `386`) sale limpio.
3. `go vet ./...` y `go test ./...` pasan.
4. La documentación de `ha4win/docs/` refleja lo implementado. Si la
   implementación se separa del diseño, se corrige el documento en el mismo commit
   y se explica por qué.
5. El commit se hace **después** de esa validación, nunca antes.

Al cerrar cada fase, informa de: qué se validó, sobre qué host, qué criterios
quedaron sin verificar y por qué.
