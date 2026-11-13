# Traspaso a Codex: ha4linux 0.5.18, actualizacion remota fiable y con progreso

Diseño de Claude. Codex: **antes de implementar, revisa este documento contra el codigo y devuelve gaps,
dudas o colisiones**; implementa solo cuando no queden abiertos.

Repositorio **publico**: ni IPs, ni nombres de equipos, ni rutas de una instalacion concreta. Ejemplos con
nombres genericos y, si hacen falta direcciones, RFC 5737 (`192.0.2.0/24`).

Rama: `ha4linux-update-progress` (desde `origin/main`, que ya incluye 0.5.17). **No hagas commit ni push.**

Entorno de pruebas: **`~/venvs/ha-addons`** (ya tiene `pytest-homeassistant-custom-component` y `ruff`). No
crees entornos ni cachés dentro del repo: `PYTHONDONTWRITEBYTECODE=1 ~/venvs/ha-addons/bin/python -m pytest
-p no:cacheprovider tests/ha4linux`.

## Orden de lectura

1. `AGENT_CONTEXT.md`.
2. `custom_components/ha4linux/update.py` (`HA4LinuxApiUpdateEntity`) y `api.py` (`update_apply`, timeouts).
3. `ha4linux/app/core/update_manager.py` (estados `idle/checking/applying/restarting/rollback/error`).
4. `ha4linux/packaging/assets/ha4linux-update-apply-worker.py` y `ha4linux-update-rollback-worker.py`.
5. `ha4linux/packaging/common/install-client.sh` (creacion del venv, ~linea 690-702).
6. `HA_INTEGRATION.md`, `CLIENT_INSTALLER.md` (seccion de actualizacion remota) y `HANDOFF_CODEX_0.5.17.md`
   como plantilla de versionado.
7. En el entorno: `homeassistant/components/update/__init__.py` (`async_install_with_progress`,
   `state_attributes`, comprobacion `entity.in_progress is not False` en el servicio `update.install`).

## Problemas observados (actualizacion 0.5.15 -> 0.5.17 en varios hosts)

**P1. La entidad no muestra el progreso real.** `HA4LinuxApiUpdateEntity` no declara
`UpdateEntityFeature.PROGRESS`, asi que HA ignora su propiedad `in_progress` y solo muestra progreso mientras
dura `async_install` (la llamada `/v1/update/apply`). Cuando el agente responde `restarting`, HA quita el
progreso y vuelve a ofrecer "Instalar" con la version antigua durante los ~10-70 s que tarda el agente en
reiniciar y volver a sondearse. Si el usuario pulsa otra vez, HA lanza "Update installation already in
progress" (porque `in_progress` si devuelve `True` con el estado `restarting` que aun conserva el
coordinador). Despues pasa sola a actualizado. Confunde.

**P2. El instalador depende del shebang de `pip`.** `install-client.sh` (lineas ~700-701) y los workers
(`rebuild_virtualenv`, lineas ~189-190 y ~62-63) ejecutan `/opt/ha4linux/.venv/bin/pip`. Si el venv se creo
con otro nombre y se renombro a `.venv`, los scripts de `bin/` apuntan a una ruta inexistente y la
actualizacion falla con 127 ("no se ha encontrado el fichero requerido"), aunque `.venv/bin/python` funcione
y el agente este en marcha. Caso real: venv creado como `.venv-<distro>-<fecha>` tras un cambio de version
mayor de la distribucion y renombrado despues.

**P3. No se restaura la copia si la instalacion falla.** En `ha4linux-update-apply-worker.py`, `main()` solo
asigna `backup_dir` si `apply_update()` termina bien, pero la copia se crea dentro de `apply_update()`. Si el
instalador falla, `backup_dir` es `None`, no se restaura nada y el host queda a medias (ficheros de la version
nueva en disco, proceso con la antigua; el siguiente reinicio cargaria codigo a medio instalar).

## Decisiones

### D1. Integracion: progreso real (P1)

- `supported_features`: con `supports_apply`, `INSTALL | SPECIFIC_VERSION | PROGRESS`.
- Estado local de "actualizacion pendiente" en la entidad: tras un `update_apply` con `ok`, guardar
  `target_version` (la que devuelve el agente o, si no, `latest_version`) y el instante de inicio.
- `in_progress` devuelve `True` si el estado del agente esta en `_IN_PROGRESS_STATES` **o** hay pendiente
  activa. La pendiente se cierra cuando:
  - `installed_version == target_version` (exito), o
  - el agente informa `state == "error"` (fallo; el atributo `error` ya lo muestra), o
  - pasan **300 s** (constante con nombre). En ese caso registrar un aviso en el log con el host y la version
    objetivo, y exponer un atributo `last_update_issue` con un texto estable ("update to X did not complete
    within 300 s"); se limpia en la siguiente actualizacion con exito.
- `update_percentage` siempre `None` (no hay porcentaje real; HA muestra progreso indeterminado). `in_progress`
  debe devolver siempre `bool`.
- Mientras dura la pendiente, el coordinador puede fallar porque el agente esta reiniciando: la entidad no debe
  pasar a `unavailable` por eso si conserva el ultimo `status` (revisa el `available` actual y el de
  `CoordinatorEntity`).
- Refrescos tras aplicar: sustituir el unico refresco a los 5 s por una secuencia (p. ej. 5, 15, 30, 60, 120,
  180, 300 s) que se detiene en cuanto se cierra la pendiente. Cancelarla si la entidad se elimina
  (`async_on_remove`). Sin bucles activos ni esperas en el bucle de eventos.
- No cambiar el contrato del agente: la integracion debe funcionar igual con agentes 0.5.15-0.5.17.

### D2. Instalador y workers: `python -m pip` y venv sano (P2)

- `install-client.sh`: sustituir `"${INSTALL_DIR}/.venv/bin/pip" ...` por
  `"${INSTALL_DIR}/.venv/bin/python" -m pip ...`.
- Antes de usarlo, comprobar que el venv es utilizable: `"${INSTALL_DIR}/.venv/bin/python" -c 'import sys'`.
  Si no lo es (interprete desaparecido tras actualizar la distribucion) o su version mayor.menor no coincide
  con la de `python3` del sistema, recrearlo con `python3 -m venv --clear` (registrar en la salida que se
  recrea y por que). Si funciona, conservarlo (sin `--clear`).
- Workers (`rebuild_virtualenv` en apply y rollback): mismo cambio a `python -m pip`.

### D3. Worker de aplicacion: restaurar siempre la copia si falla (P3)

- Crear la copia **antes** de cualquier paso que modifique el sistema y tenerla disponible en el `except`: por
  ejemplo, `main()` enriquece la peticion, llama a `create_backup()` y despues a `apply_update(request,
  backup_dir)`.
- Si la restauracion tambien falla, registrar ambos errores y salir con codigo distinto de 0 (no ocultar el
  primero).
- **Efecto diferido**: el worker que se ejecuta en una actualizacion es el **ya instalado** en el host
  (`/opt/ha4linux/update/`), no el del bundle nuevo. D3 protege a partir de la actualizacion siguiente a
  0.5.18; D2 en `install-client.sh` si actua desde ya (viene en el bundle). Documentarlo en el changelog.

### D4. Versiones

- Agente 0.5.17 -> **0.5.18** y bundle `update-assets/ha4linux-client-update-0.5.18.tar.gz` con
  `build-update-bundle.sh` (generarlo al final; SHA-256 del fichero final en `ha4linux/update-manifest.json`).
  Ficheros con la version del agente: los mismos que en 0.5.17 (`app/main.py`, `config.json`,
  `packaging/arch/PKGBUILD`; localizalos con `grep -rn '0\.5\.17' ha4linux/` excluyendo `update-assets/` y
  docs historicos).
- Integracion 0.5.17 -> **0.5.18**: `const.py`, `manifest.json`, `custom_components/ha4linux/update-manifest.json`.
- Schema `1.0` y rango `0.3.0`-`0.6.x` sin cambios.

### D5. Pruebas (`tests/ha4linux/`)

Integracion (con HA):
- `supported_features` incluye `PROGRESS` con `supports_apply` y no incluye nada sin el.
- Tras `update.install` con apply `ok` y agente en `restarting`: `in_progress` sigue `True` aunque el
  coordinador falle un refresco; pasa a `False` y estado `off` cuando `installed_version` llega al objetivo.
- Pendiente que expira a los 300 s (tiempo simulado): `in_progress=False`, `last_update_issue` presente.
- Agente en `error` tras aplicar: se cierra la pendiente.
- `update.install` durante la pendiente: error "already in progress" (comportamiento de HA, esperado).
- Agente antiguo (sin cambios en el payload): sin regresiones.

Workers e instalador (sin HA):
- `ha4linux-update-apply-worker.py` (cargar con `importlib` por el guion del nombre): si `apply_update` falla
  despues de crear la copia, se llama a `restore_backup` con ella; si la restauracion falla, el error final
  incluye ambos.
- Ningun script de `packaging/` invoca `.venv/bin/pip` directamente (prueba de texto sencilla).
- Si es viable sin root, prueba de la funcion de comprobacion del venv de `install-client.sh` aislada (si no,
  documenta como se valido).

Linters: `~/venvs/ha-addons/bin/ruff check` sobre lo tocado; no introducir avisos (salvo los de
compatibilidad con Python 3.9 en el agente, p. ej. `datetime.UTC`, que no deben aplicarse).

### D6. Documentacion

- `HA_INTEGRATION.md`: como se ve ahora una actualizacion (progreso hasta que el agente vuelve, limite de 300 s,
  `last_update_issue`).
- `CLIENT_INSTALLER.md`: `python -m pip`, recreacion automatica del venv roto y efecto diferido de D3.
- README del agente: changelog 0.5.18.

## Resoluciones de la revision de gaps (fase 1 de Codex)

Prevalecen sobre D1-D6 donde los contradigan.

1. **Progreso desde el inicio.** La pendiente se abre al **empezar** `async_install` (antes de `update_check`),
   con `target_version = version solicitada o latest_version`, y se publica el estado
   (`async_write_ha_state`). Si `update_check` o `update_apply` fallan (excepcion o `ok: false`), se cierra la
   pendiente, se publica el estado y se relanza `HomeAssistantError` como hoy.
2. **Prioridad al cierre.** Regla de `in_progress`:
   - pendiente activa -> `True`;
   - si no, el estado del agente en `_IN_PROGRESS_STATES` cuenta **solo si el ultimo refresco del coordinador
     fue correcto** (`coordinator.last_update_success`), para que datos conservados de un agente que reinicia
     (`restarting`) no mantengan el progreso tras vencer o cerrar la pendiente.
3. **Que cierra la pendiente**, evaluado en este orden en cada actualizacion del coordinador:
   a) `installed_version == target_version` -> exito (limpia `last_update_issue`);
   b) refresco correcto y payload del agente real (`enabled` verdadero, `state == "error"`, y `last_applied_at`
   no posterior al inicio de la pendiente **o** `error` no vacio) -> fallo de aplicacion;
   c) 300 s -> vencida (aviso en log y `last_update_issue`).
   Un refresco fallido o el payload sintetico de `api.update_status()` (fallo de transporte, `enabled=False`)
   **no** cierran la pendiente.
4. **Disponibilidad.** Con pendiente activa, la entidad esta disponible aunque el coordinador falle o el payload
   sea sintetico (se usan los ultimos datos validos conocidos para versiones y atributos). Sin pendiente, se
   mantiene la regla actual.
5. **Restauracion completa (worker de aplicacion).** Inventaria lo que modifica `install-client.sh` y amplia
   `BACKUP_PATHS` para cubrirlo. Los directorios que pertenecen por completo a ha4linux (`/opt/ha4linux/app`,
   `/opt/ha4linux/tray`, `/opt/ha4linux/update` y similares que encuentres) se restauran **sustituyendolos**
   (no copiando encima), para retirar ficheros nuevos. La configuracion de `/etc/ha4linux` se restaura
   copiando encima (no borrar ficheros del usuario). El venv **no** entra en la copia; se trata en el punto 6.
   Actualiza `CLIENT_INSTALLER.md` para que diga exactamente que se restaura.
6. **Venv sano, sin destruir uno que funciona** (instalador y ambos workers, con la misma logica; si puedes,
   compartida en un unico script o funcion reutilizable dentro de `packaging/`):
   - sano = `.venv/bin/python` ejecuta **y** `.venv/bin/python -m pip --version` funciona;
   - si esta sano: `python -m pip install -r requirements.txt` sobre el;
   - si no: crear un venv nuevo en un directorio temporal junto al actual (`.venv.new-<ts>`) con el `python3`
     del sistema, instalar requisitos alli y, **solo si todo funciona**, sustituir (`.venv` ->
     `.venv.old-<ts>`, `.venv.new-<ts>` -> `.venv`; retirar el antiguo al final o dejar solo el ultimo). Si
     algo falla, borrar el temporal, dejar `.venv` como estaba y salir con un error que explique la causa
     (p. ej. falta el modulo `venv` y como instalarlo).
   - El instalador inicial (sin venv previo) mantiene su flujo normal.
7. **Sin recrear por diferencia de version.** Se elimina el criterio "version mayor.menor distinta" de D2: solo
   se recrea si no esta sano. Version minima de Python admitida: 3.9 (la del soporte de bullseye); comprobarla
   en el `python3` del sistema antes de crear un venv nuevo.
8. Cubierto por el punto 6 (la comprobacion incluye `pip`).
9. **Prueba de doble instalacion.** Probar que una segunda llamada a `update.install` durante la pendiente no
   lanza un segundo `update_apply` y termina en `HomeAssistantError`, sin fijar el texto exacto.

## Validacion funcional (no la hace Codex)

La hacen el usuario y Claude despues: integracion 0.5.18 en un HA real y actualizacion de un agente pendiente
observando el estado de la entidad; actualizacion de un host con venv renombrado.

## Definicion de terminado (para Codex)

- [ ] Informe de gaps entregado y resuelto antes de implementar.
- [ ] D1-D6 implementados en la rama, sin commit.
- [ ] `pytest` en verde con `~/venvs/ha-addons` (indica cuantas pruebas y si se ejecutaron las `test_ha_*`).
- [ ] Sin datos de ninguna instalacion concreta y sin entornos ni cachés nuevos dentro del repo.
- [ ] Resumen final: ficheros tocados, decisiones tomadas en puntos no cubiertos aqui, y pendientes.
