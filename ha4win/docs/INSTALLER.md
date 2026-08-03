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
| `--allow <cidr,...>` | vacío | Allowlist de clientes |
| `--no-tls` | — | Desactiva TLS. Exige confirmación o `--force` |
| `--no-firewall` | — | No crea la regla de firewall |
| `--no-start` | — | Instala sin arrancar (equivalente al `--no-start` de ha4linux) |
| `--config <ruta>` | `C:\ProgramData\HA4Win\config.json` | Ruta alternativa |
| `--san <host,ip>` | hostname + IPs locales | SAN adicionales del certificado |
| `--quiet` | — | Salida mínima, apta para despliegue desatendido |

## Secuencia de instalación

1. **Verificar elevación.** Sin token de administrador se aborta con instrucción
   clara. No se intenta autoelevar.
2. **Verificar la versión de Windows** contra la matriz de soporte. Por debajo del
   mínimo se aborta.
3. **Crear directorios**: `C:\Program Files\HA4Win`, `C:\ProgramData\HA4Win\{state,certs,logs,update}`.
4. **Aplicar DACL** sobre `C:\ProgramData\HA4Win`: herencia rota, solo SYSTEM y
   Administrators (ver [CONFIGURATION.md](CONFIGURATION.md#permisos-del-fichero)).
5. **Copiar el binario** a `C:\Program Files\HA4Win\ha4win.exe`. Si ya existe una
   instalación, se conserva el `config.json` existente.
6. **Escribir `config.json`** con el token —generado si no se pasó— si no existe ya.
7. **Generar certificado autofirmado** con `crypto/x509`: clave ECDSA P-256, SAN con
   hostname, FQDN e IPs locales, validez 10 años. Sin OpenSSL.
8. **Registrar el origen del Event Log** `HA4Win`.
9. **Registrar el servicio** en el SCM: arranque automático, cuenta LocalSystem,
   descripción, y acciones de recuperación (reinicio a los 5 s / 10 s / 60 s con
   reset del contador a las 24 h).
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
existente actualiza el binario y el servicio sin tocar configuración ni certificado.

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
