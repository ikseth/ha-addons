# Actualización remota

Mismo contrato que ha4linux: manifiesto con versión, artefacto y `sha256`,
comprobación periódica, aplicación desde Home Assistant, rollback local
automático. Cambia el mecanismo de aplicación, que en Windows es sensiblemente
más simple.

**Desactivado por defecto** (`management.remote_update.enabled: false`).

## Por qué es más simple que en Linux

En ha4linux la aplicación necesita salir del sandbox de `ha4linux.service` con
`systemd-run`, un worker transitorio, helpers root y un preflight que detecta
arranques desde snapshot Btrfs. En Windows nada de eso aplica:

- El servicio corre como LocalSystem sin sandbox de sistema de ficheros.
- **Windows permite renombrar un ejecutable en uso.** No se puede sobrescribir,
  pero sí `MoveFileExW`. Eso da un swap por rename y un rollback triviales.
- El SCM ya sabe parar y arrancar el servicio, y reintenta si el arranque falla. El
  aplicador lo gobierna con la **API SCM** (`OpenSCManager`, `OpenService`,
  `ControlService`, `StartService`, `QueryServiceStatusEx`), **no** con `sc.exe`:
  ejecutar procesos externos en runtime está prohibido por diseño, y esta regla no
  admite excepción ni siquiera en el updater.

El resultado es que no hace falta ningún artefacto externo: **el propio binario se
actualiza a sí mismo**.

## Manifiesto

Formato idéntico al de ha4linux, incluido el soporte de canales:

```json
{
  "version": "0.2.0",
  "changelog_url": "https://github.com/ikseth/ha-addons/releases/tag/ha4win-v0.2.0",
  "asset_url": "https://raw.githubusercontent.com/ikseth/ha-addons/main/ha4win/update-assets/ha4win-0.2.0-windows-amd64.zip",
  "sha256": "…",
  "min_windows_build": 14393
}
```

Con canales:

```json
{
  "channels": {
    "stable": { "version": "0.2.0", "asset_url": "…", "sha256": "…" },
    "beta":   { "version": "0.3.0-rc1", "asset_url": "…", "sha256": "…" }
  }
}
```

Diferencias respecto de ha4linux:

- El artefacto es un **ZIP por arquitectura**. El agente resuelve el sufijo de su
  propia arquitectura (`amd64`/`arm64`/`386`) si el `asset_url` contiene el
  marcador `{arch}`; si no, usa la URL literal.
- `min_windows_build` (opcional) permite publicar una versión que se autoexcluye en
  hosts antiguos: el host la ve pero declara `update_available: false` con motivo,
  en vez de intentar aplicar algo que no arrancará.

Se conserva el truco de ha4linux de añadir un parámetro de query con marca de
tiempo redondeada a 30 s para evitar el retardo de caché de `raw.githubusercontent`.

## GET /v1/update/status

```json
{
  "ok": true,
  "supported": true,
  "enabled": true,
  "readonly_mode": false,
  "allow_in_readonly": false,
  "state": "idle",
  "installed_version": "0.1.0",
  "target_version": "0.2.0",
  "update_available": true,
  "channel": "stable",
  "manifest_url": "…",
  "changelog_url": "…",
  "asset_url": "…",
  "asset_sha256": "…",
  "last_checked_at": "2026-08-03T09:58:00Z",
  "last_applied_at": null,
  "last_error": null,
  "supports_apply": true,
  "supports_rollback": true,
  "supports_apply_reason": null,
  "rollback_version": "0.1.0",
  "preflight": { }
}
```

Campos y estados idénticos a ha4linux para que la entidad `update` de la
integración sea la misma lógica. `rollback_version` es una adición: la versión a la
que volvería `rollback`, o `null` si no hay binario anterior guardado.

Estados: `idle`, `checking`, `downloading`, `verifying`, `applying`, `restarting`,
`rollback`, `error`, `disabled`.

## Preflight

Sustituye a las comprobaciones de systemd/Btrfs de Linux:

| Comprobación | Bloquea `apply` |
| --- | --- |
| Ejecutándose como servicio bajo el SCM (no en modo `run`) | Sí |
| Directorio de instalación escribible por el proceso | Sí |
| Espacio libre ≥ 3× el tamaño del artefacto en `ProgramData\HA4Win\update` | Sí |
| No hay otra actualización en curso | Sí |
| `asset_url` presente en el manifiesto | Sí |
| Build de Windows ≥ `min_windows_build` | Sí |
| Arquitectura del artefacto coincide con la del host | Sí |
| `readonly_mode` activo sin `allow_in_readonly` | Sí |
| Firma Authenticode válida, si `require_signed_asset` | Sí |
| Reinicio pendiente del sistema | No, solo aviso |

Se expone en `preflight.checks` con la misma forma que ha4linux, de modo que la
integración pueda mostrar el motivo exacto por el que un host no puede aplicar.

## Flujo de `apply`

`POST /v1/update/apply` acepta opcionalmente `{"target_version": "0.2.0"}`. Sin él,
se aplica la versión del manifiesto y solo si `update_available` es `true`. Si se
proporciona, **debe coincidir exactamente con la versión seleccionada del manifiesto
vigente** (el que se acaba de refrescar en el paso `check`); cualquier otro valor
devuelve error. No hay índice histórico de artefactos: solo se puede aplicar lo que
el manifiesto ofrece ahora. En todo caso la versión destino debe ser
**estrictamente mayor** que la instalada: el downgrade no está soportado, igual que
en ha4linux. El parámetro existe para confirmación explícita ("aplica exactamente
0.2.0"), no para elegir una versión arbitraria.


1. **check** — refresca el manifiesto y revalida el preflight.
2. **downloading** — descarga a `ProgramData\HA4Win\update\ha4win-<version>.zip`,
   con límite de tamaño (64 MiB) y timeout.
3. **verifying** — `sha256` obligatorio; firma Authenticode si está exigida;
   extracción del `ha4win.exe` a `update\staging\`; ejecución de
   `staging\ha4win.exe version` para confirmar que el binario arranca y que la
   versión coincide con la del manifiesto. **Un artefacto que no se puede ejecutar
   se descarta aquí, antes de tocar la instalación.**
4. **applying** — se escribe `update\update-state.json` con la operación en curso y
   se lanza el binario *en staging* con `update apply --from-service`, como proceso
   independiente (`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`). El servicio
   responde a Home Assistant y se prepara para morir.
5. El proceso aplicador realiza el swap. **El orden importa: primero se coloca el
   binario nuevo en un temporal del mismo directorio, y solo al final se promueve
   con un rename**, de modo que nunca hay una ventana sin `ha4win.exe` ni una copia
   a medias sobre el nombre definitivo:
   - Copia el binario validado (desde `staging\`) a
     `Program Files\HA4Win\ha4win.exe.new` y hace *flush* a disco. Esta copia puede
     ser parcial sin consecuencia: aún no es el ejecutable del servicio.
   - Para el servicio con `ControlService(STOP)` y espera a `SERVICE_STOPPED` (60 s;
     si no para, aborta, borra `.new` y deja todo como estaba).
   - `MoveFileExW` de `ha4win.exe` → `ha4win.exe.previous` (reemplazando el
     `.previous` anterior si lo hubiera).
   - `MoveFileExW` de `ha4win.exe.new` → `ha4win.exe` (`MOVEFILE_REPLACE_EXISTING`).
     Esta segunda operación es el punto de conmutación y es un rename, no una copia.
   - `StartService`.
   - Si el segundo `MoveFileExW` fallara, se restaura de inmediato `.previous` sobre
     `ha4win.exe` y se arranca.
6. **restarting → health-check** — el aplicador sondea `GET /health` sobre el **bind
   efectivo**, no `127.0.0.1` a ciegas: si `bind_host` es `0.0.0.0` o `::` sondea
   loopback; si es una IP concreta, sondea esa IP. Con TLS activo la sonda no valida
   la cadena (es el propio certificado autofirmado local); solo comprueba que el
   endpoint responde `{"status":"ok"}`. Plazo `health_check_timeout_sec` (60 s).
   - **Éxito**: actualiza `update-state.json` con `result: "success"`, conserva
     `.previous` para un rollback manual y borra el staging y `.new`.
   - **Fallo**: para el servicio, restaura `.previous` sobre `ha4win.exe`, arranca
     y marca `result: "rolled_back"` con el motivo.
7. Al arrancar, el servicio lee `update-state.json` y publica el desenlace en
   `/v1/update/status` (`last_applied_at`, `last_error`). Así Home Assistant ve qué
   pasó aunque la petición HTTP original se cortara con el reinicio.

## Flujo de `rollback`

Promueve `ha4win.exe.previous` a `ha4win.exe` con el mismo mecanismo: copia a
`.new`, parada por API SCM, rename del actual y promoción por `MoveFileExW`,
arranque y health-check al bind efectivo. Si no existe `.previous`, devuelve
`ok: false` con `"no previous version available"` sin tocar nada.

## Garantías

| Garantía | Cómo |
| --- | --- |
| Nunca hay una ventana sin `ha4win.exe` | El binario nuevo se coloca en `.new` y solo se conmuta con un rename final; nunca se copia sobre el nombre definitivo |
| Nunca se destruye la versión en ejecución | El actual pasa a `.previous` por rename antes de promover el nuevo |
| Nunca se aplica un artefacto corrupto | `sha256` + arranque de prueba (`staging\ha4win.exe version`) antes del swap |
| Nunca queda un host sin servicio | Health-check al bind efectivo con restauración automática de `.previous` |
| El resultado es observable tras el reinicio | `update-state.json` persistente |
| Dos `apply` simultáneos no se pisan | Lock por fichero en `update\` con PID |
| Ningún proceso externo en runtime | El servicio se gobierna por API SCM, no por `sc.exe` |

## Publicación de una versión

```bash
./build/build.sh 0.2.0                       # matriz de arquitecturas + SHA256SUMS
./build/build-update-asset.sh 0.2.0          # zip por arquitectura en update-assets/
./build/render-update-manifest.sh 0.2.0 stable > update-manifest.json
```

Mismo patrón que `packaging/scripts/build-update-bundle.sh` y
`render-update-manifest.sh` de ha4linux, con los artefactos versionados en
`ha4win/update-assets/`.

### Política de versionado

Agente e integración van **en paralelo**, como en ha4linux (ambos en `0.5.15`): una
release sube las dos versiones aunque solo cambie una de las partes. Es lo que hace
legible la matriz de compatibilidad `min/max_integration_version` y lo que evita
tener que razonar sobre combinaciones cruzadas al diagnosticar un host.

Ambos arrancan en `0.1.0`. "En paralelo" es **absoluto**: cada release sube la
versión y actualiza el manifiesto de **ambas** partes aunque solo cambie una, sin
excepción. Así no hay que razonar sobre combinaciones cruzadas al diagnosticar un
host.

Al publicar hay que actualizar, en el mismo commit, **siempre los cinco**:

- `internal/version/version.go` (o el valor inyectado por `ldflags`)
- `ha4win/update-manifest.json`
- `custom_components/ha4win/const.py`
- `custom_components/ha4win/manifest.json`
- `custom_components/ha4win/update-manifest.json`
