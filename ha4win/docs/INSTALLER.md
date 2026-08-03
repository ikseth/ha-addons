# Instalación, build y distribución

## Principio

No hay instalador separado. El binario **es** el instalador. Se copia un fichero al
host y se ejecuta un subcomando. Sin MSI, sin Inno Setup, sin PowerShell, sin
descargas durante la instalación.

Esto importa porque el caso difícil —hosts securizados— es justo donde
`Set-ExecutionPolicy`, AppLocker o Constrained Language Mode bloquean scripts, y
donde un instalador empaquetado dispara la heurística del EDR.

## Subcomandos

```
ha4win.exe install     [flags]   Instala y registra el servicio
ha4win.exe uninstall   [--purge] Desinstala; --purge borra también ProgramData
ha4win.exe service               Punto de entrada del SCM (uso interno)
ha4win.exe run         [flags]   Ejecuta en primer plano, log a consola
ha4win.exe start | stop | restart Control del servicio vía SCM
ha4win.exe status                Estado del servicio y sonda local a /health
ha4win.exe version               Versión, commit, fecha de build
ha4win.exe config print          Configuración efectiva, token censurado
ha4win.exe config validate       Valida y devuelve código de salida
ha4win.exe cert generate [--force] [--san host,ip]
ha4win.exe cert show             Huella y validez del certificado actual
ha4win.exe update apply --asset <ruta|url> --sha256 <hex>
ha4win.exe update rollback
```

### Flags de `install`

| Flag | Defecto | Descripción |
| --- | --- | --- |
| `--token <valor>` | — | Token de API. Si se omite, se genera uno de 32 bytes y se imprime |
| `--port <n>` | `8099` | Puerto de escucha |
| `--bind <ip>` | `0.0.0.0` | Dirección de escucha |
| `--allow <cidr,...>` | vacío | Allowlist de clientes. **Recomendado** fijar la IP de Home Assistant (ver nota de seguridad más abajo) |
| `--no-tls` | — | Desactiva TLS. Exige confirmación o `--force` |
| `--no-firewall` | — | No crea la regla de firewall |
| `--no-start` | — | Instala sin arrancar (equivalente al `--no-start` de ha4linux) |
| `--config <ruta>` | `C:\ProgramData\HA4Win\config.json` | Ruta alternativa del `config.json` |
| `--san <host,ip>` | hostname + IPs locales | SAN adicionales del certificado |
| `--reconfigure` | — | Permite que los flags reescriban un `config.json` existente (ver política de reinstalación) |
| `--quiet` | — | Salida mínima, apta para despliegue desatendido |

**Política de flags en reinstalación.** Los flags de configuración (`--token`,
`--port`, `--bind`, `--allow`, `--san`, `--no-tls`) **solo se aplican en la primera
instalación**. Si ya existe `config.json`, se conserva intacto y los flags de
configuración se **ignoran con un aviso explícito** que nombra cada flag ignorado.
Para reconfigurar en una reinstalación hay que pasar `--reconfigure`, que reescribe
de forma atómica solo los campos indicados. Es la política predecible: reinstalar
para actualizar el binario nunca cambia la configuración por sorpresa. Los flags
operativos (`--no-start`, `--no-firewall`, `--quiet`, `--config`) sí se respetan
siempre, porque afectan a la acción de instalar, no al contenido de la config.

**Seguridad — allowlist recomendada.** En instalación no silenciosa, si `--allow`
está vacío el instalador **avisa** de que la API quedará accesible desde cualquier
origen de la red y **recomienda** limitarla a la IP de Home Assistant. No lo impone
(no siempre se conoce la IP en el momento de instalar), pero lo deja anotado en el
resumen final. Ver [SECURITY.md](SECURITY.md#endurecimiento-adicional-recomendado).

## Secuencia de instalación

1. **Verificar elevación.** Sin token de administrador se aborta con instrucción
   clara. No se intenta autoelevar.
2. **Verificar la versión de Windows** contra la matriz de soporte. Por debajo del
   mínimo se aborta.
3. **Crear directorios**: `C:\Program Files\HA4Win`, `C:\ProgramData\HA4Win\{state,certs,logs,update}`.
4. **Aplicar DACL** sobre `C:\ProgramData\HA4Win`: herencia rota, solo SYSTEM y
   Administrators (ver [CONFIGURATION.md](CONFIGURATION.md#permisos-del-fichero)).
5. **Instalar el binario de forma transaccional** en
   `C:\Program Files\HA4Win\ha4win.exe`. Windows no permite sobrescribir un
   ejecutable en uso, así que la copia sigue el mismo mecanismo que el updater (ver
   [UPDATER.md](UPDATER.md#flujo-de-apply)):
   - Primera instalación (no existe `ha4win.exe`): copiar directamente.
   - Reinstalación con el servicio corriendo: copiar el binario nuevo a un temporal
     en el mismo directorio, parar el servicio y esperar a que pare (60 s; si no
     para, abortar sin tocar nada), renombrar el actual a `ha4win.exe.previous`,
     promover el temporal con `MoveFileExW`, y arrancar. Si el arranque o el
     health-check fallan, restaurar `.previous` y dejar el servicio como estaba.
   - Si el binario origen es idéntico al instalado (mismo SHA-256), se omite la
     copia y solo se revalida el servicio.
6. **Escribir `config.json`** con el token —generado si no se pasó— **solo si no
   existe**. Si existe, se conserva (ver política de flags en reinstalación); con
   `--reconfigure` se reescriben atómicamente los campos indicados por flags.
7. **Generar certificado autofirmado** con `crypto/x509`, solo si no existe ya el
   par (ver perfil X.509 normativo en
   [CONFIGURATION.md](CONFIGURATION.md#certificado-tls)). Sin OpenSSL.
8. **Registrar el origen del Event Log** `HA4Win`.
9. **Registrar el servicio** en el SCM con este contrato exacto:
   - `BinaryPathName`: `"C:\Program Files\HA4Win\ha4win.exe" service`. Si se instaló
     con `--config <ruta>` no estándar, se añade `--config "<ruta absoluta>"`.
   - Cuenta `LocalSystem`, `SERVICE_AUTO_START`, tipo `SERVICE_WIN32_OWN_PROCESS`.
   - Acciones de recuperación: reinicio a los 5 s / 10 s / 60 s, reset del contador
     a las 24 h.
   - En reinstalación se hace `ChangeServiceConfig` sobre el servicio existente en
     lugar de recrearlo, para no perder dependencias ni ajustes manuales.
10. **Crear la regla de firewall** de entrada para el puerto TCP, perfiles Domain y
    Private, invocando `netsh advfirewall firewall add rule` con argumentos fijos.
    Es la **única** invocación de un proceso externo en todo el producto y ocurre
    solo durante la instalación, nunca en ejecución: la regla de "sin procesos
    externos" acota la superficie del servicio en marcha, no la del instalador.
    Sustituirlo por `INetFwPolicy2` (COM) queda como mejora opcional de la fase 6,
    para no meter dependencia de COM en la fase 0.
11. **Arrancar el servicio** salvo `--no-start` y **verificar** `GET /health` en
    local durante 15 s.
12. **Imprimir el resumen**: token, URL, huella SHA-256 del certificado. Es lo que
    hay que introducir en Home Assistant.

Toda la secuencia es idempotente: reejecutar `install` sobre una instalación
existente actualiza el binario y revalida el servicio sin tocar configuración ni
certificado (salvo `--reconfigure`).

## Ciclo de vida del servicio (contrato SCM)

`ha4win.exe service` es el punto de entrada que el SCM invoca. Contrato:

- **Directorio de trabajo**: irrelevante; todas las rutas del agente son absolutas.
- **Arranque**: reporta `SERVICE_START_PENDING` con checkpoints incrementales
  mientras carga configuración, valida y abre el listener TLS; luego
  `SERVICE_RUNNING`. Plazo de arranque anunciado al SCM: 30 s. Si la validación de
  configuración falla, registra el motivo en el Event Log y sale con código ≠ 0, y
  el SCM aplica la política de recuperación.
- **Controles admitidos**: `SERVICE_CONTROL_STOP` y `SERVICE_CONTROL_SHUTDOWN`
  disparan un apagado ordenado del servidor HTTP (`http.Server.Shutdown` con
  drenaje de peticiones en curso, plazo 10 s) antes de reportar `SERVICE_STOPPED`.
  Plazo de parada anunciado: 15 s.
- **Códigos de salida** (para `run`/`service` fuera del SCM y para diagnóstico):
  `0` salida limpia; `1` error de configuración; `2` error de TLS/certificado;
  `3` puerto en uso; `4` invocado como `service` fuera del contexto del SCM.
- **`ha4win.exe run`** ejecuta el mismo servidor en primer plano con log a consola,
  sin hablar con el SCM; es la vía de depuración y **no** cumple el preflight del
  updater (que exige ejecución bajo el SCM).

## Desinstalación

`ha4win.exe uninstall` detiene y elimina el servicio, borra la regla de firewall y
el origen del Event Log, y elimina `C:\Program Files\HA4Win`. **Conserva**
`C:\ProgramData\HA4Win` salvo `--purge`, para no perder configuración ni
certificado en una reinstalación.

## Matriz de compatibilidad

| Windows | Soporte | Toolchain |
| --- | --- | --- |
| Windows 11 (todas las builds) | Completo | Go actual |
| Windows 10 1607+ | Completo | Go actual |
| Windows Server 2016 / 2019 / 2022 / 2025 | Completo | Go actual |
| Windows Server Core (2016+) | Completo | Go actual |
| Windows 8.1 / Server 2012 R2 | Best effort, build legacy | Go 1.20.14 |
| Windows 7 SP1 / Server 2008 R2 | Best effort, build legacy | Go 1.20.14 |

Go 1.21 retiró el soporte de Windows 7/8/Server 2008/2012. Por eso la rama legacy
se compila con **Go 1.20.14**, el último toolchain que los soporta. El código debe
evitar API introducidas después de Go 1.20 y encapsular tras build tags cualquier
llamada Win32 no disponible en esos sistemas (`GetIfTable2` existe desde Vista;
`GetSystemPowerStatus` y el SCM también). La rama legacy se compila en CI pero se
declara *best effort*: se publica sin garantía de validación en hardware real.

Arquitecturas: `amd64` (principal), `arm64` (Windows on ARM), `386` (equipos
antiguos de 32 bits).

**Alcance de validación por arquitectura.** La Fase 0 se da por soportada
**funcionalmente solo en amd64 moderno**. `arm64` y `386` se compilan como
comprobación de que el código es portable, pero su validación funcional no es
requisito de cierre de las fases 0–5. El build legacy (Go 1.20.14) queda para la
fase 6 y **fija una versión máxima de `golang.org/x/sys`** compatible con ese
toolchain: el `go.mod` de la rama principal usa la `x/sys` actual y la rama legacy
la reduce a la última compatible con Go 1.20, en artefactos separados.

## Build

Compilación cruzada desde el equipo de desarrollo Linux. No se necesita Windows en
ningún punto del proceso.

```bash
# build/build.sh
MODULE=github.com/ikseth/ha-addons/ha4win
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 \
  go build -trimpath \
    -ldflags "-s -w \
      -X ${MODULE}/internal/version.Version=${VERSION} \
      -X ${MODULE}/internal/version.Commit=$(git rev-parse --short HEAD) \
      -X ${MODULE}/internal/version.BuildDate=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -o dist/ha4win-${VERSION}-windows-amd64/ha4win.exe ./cmd/ha4win
```

- `CGO_ENABLED=0` garantiza el enlazado estático puro.
- `-trimpath` elimina rutas absolutas del build: reproducibilidad y menos ruido en
  los análisis estáticos.
- `-s -w` recorta la tabla de símbolos: ~35 % menos de tamaño.
- **Nunca** usar UPX ni ningún empaquetador: es el mayor generador de falsos
  positivos de antivirus.

Salidas de `build.sh`: la matriz completa de arquitecturas, cada una en su
directorio, más un `SHA256SUMS`.

### Firma Authenticode (opcional pero recomendada)

En hosts securizados con SmartScreen o WDAC, un binario sin firmar añade fricción.
La firma se puede hacer desde Linux con `osslsigncode`, así que no rompe el flujo
de build cruzado:

```bash
osslsigncode sign -pkcs12 cert.pfx -pass "$PFX_PASS" \
  -n "HA4Win Workstation API" -i https://github.com/ikseth/ha-addons \
  -t http://timestamp.digicert.com \
  -in dist/.../ha4win.exe -out dist/.../ha4win-signed.exe
```

El paso es opcional y condicional a que exista el certificado; el build sin firma
debe seguir funcionando. Si `management.remote_update.require_signed_asset` está
activo, el updater verifica la firma con `WinVerifyTrust` antes de aplicar.

## Distribución

### Vía primaria

`ha4win-<version>-windows-<arch>.zip` con un solo fichero dentro: `ha4win.exe`.
El operador lo descomprime y ejecuta `install`. Es también el formato exacto que
consume el updater remoto, de modo que hay **un solo artefacto** para instalación
inicial y actualización.

### Vía secundaria (fase 6, opcional)

MSI generado con WiX v5, que se ejecuta como herramienta .NET **en el equipo de
build** (también en Linux), no en el host. El MSI se limita a:

1. Dejar `ha4win.exe` en `C:\Program Files\HA4Win`.
2. Ejecutar `ha4win.exe install --quiet --token=[HA4WIN_TOKEN]` como acción
   personalizada.
3. Ejecutar `ha4win.exe uninstall` en la desinstalación.

Existe únicamente para despliegue por GPO/Intune, donde el formato MSI es un
requisito del canal, no una necesidad técnica del producto.

## Verificación posterior a la instalación

```powershell
sc.exe query ha4win
ha4win.exe status
curl.exe -k https://localhost:8099/health
curl.exe -k -H "Authorization: Bearer <token>" https://localhost:8099/v1/sensors
```

`curl.exe` está en caja desde Windows 10 1803. En hosts anteriores,
`ha4win.exe status` cubre la misma comprobación sin dependencias.
