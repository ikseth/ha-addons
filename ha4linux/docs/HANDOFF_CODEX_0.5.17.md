# Traspaso a Codex: ha4linux 0.5.17, ultima ejecucion de unidades systemd

Diseño cerrado por Claude y validado por el usuario. Codex: **antes de implementar, revisa este documento
contra el codigo y devuelve gaps, dudas o colisiones**; implementa solo cuando no queden abiertos.

Repositorio **publico**: ni IPs, ni nombres de equipos, ni rutas de una instalacion concreta en codigo,
documentacion, pruebas o mensajes de commit. En ejemplos usa nombres genericos (`backup.timer`,
`backup.service`) y, si hacen falta direcciones, el rango RFC 5737 (`192.0.2.0/24`).

Rama: `ha4linux-unit-last-run` (creada desde `origin/main`). **No hagas commit ni push**: el usuario
valida antes.

## Orden de lectura

1. `AGENT_CONTEXT.md` (directrices del repo).
2. `ha4linux/app/sensors/services.py` (agente, sensor a ampliar).
3. `custom_components/ha4linux/sensor.py`: `HA4LinuxServiceSensor` (~linea 715), `_services_items`, y el alta
   dinamica de entidades de servicio en `async_setup_entry` (~linea 336-360).
4. `ha4linux/app/main.py` (constantes `API_*`) y el commit `6c33aac` (*Release ha4linux 0.5.15*) como
   plantilla de los ficheros que toca una version del agente.
5. Commit `bbc07e6` (0.5.16, solo integracion) como plantilla de versionado de la integracion y de pruebas.
6. `tests/ha4linux/` (`conftest.py`, `test_system_updates.py` sin HA, `test_ha_system_updates.py` con HA).

## Problema

`ServicesSensor` solo publica el estado actual (`ActiveState`/`SubState`). Un `oneshot` lanzado por un timer
queda `inactive/dead` tanto si se ejecuto bien como si nunca se ejecuto. Se necesita saber desde Home
Assistant **cuando se ejecuto por ultima vez y con que resultado**, para un "latido" (avisar si una tarea
programada lleva mas de N dias sin ejecutarse) y para detectar fallos.

## Hechos verificados (systemd 261, maquina de diseño)

```
$ LC_ALL=C TZ=UTC systemctl show -p Id,Result,ExecMainStartTimestamp,ExecMainExitTimestamp,\
ExecMainStatus,LastTriggerUSec,NextElapseUSecRealtime,LoadState x.service x.timer nope.service
Id=x.service
LoadState=loaded
Result=success
ExecMainStartTimestamp=
ExecMainExitTimestamp=
ExecMainStatus=0

Id=x.timer
LoadState=loaded
NextElapseUSecRealtime=Fri 2026-11-13 23:56:04 UTC
LastTriggerUSec=Fri 2026-11-13 07:21:48 UTC
Result=success

Id=nope.service
LoadState=not-found
Result=success
ExecMainStartTimestamp=
ExecMainExitTimestamp=
ExecMainStatus=0
```

Consecuencias de diseño:

- **El orden de salida lo decide systemd, no `--property`.** El codigo actual (`--value` + posicion) funciona
  por casualidad. Hay que pasar a `Clave=valor` y parsear a diccionario.
- Las propiedades que no aplican al tipo de unidad **no aparecen** (el timer no tiene `ExecMain*`). Ausente
  equivale a `null`.
- `ExecMainStatus=0` aparece **aunque el servicio no se haya ejecutado nunca** (o la unidad no exista). Solo
  es significativo si hay `ExecMainStartTimestamp`.
- El servicio de ejemplo **se habia ejecutado** (lo disparo su timer a las 07:21) y aun asi sus `ExecMain*`
  estan vacios: systemd pierde ese estado en memoria cuando la unidad se descarga (GC), en `daemon-reload` o
  al reiniciar. **El latido fiable es `LastTriggerUSec` del timer** (persistente entre reinicios con
  `Persistent=true`). Documentarlo.
- `--timestamp=unix` existe desde systemd 248. **El repo soporta Debian bullseye (systemd 247, commit
  `f34e8bb`)**, asi que no se puede depender de el.

## Decisiones (validadas)

### D1. Lectura de propiedades y fechas

- Una llamada por unidad, como hoy (mantiene el aislamiento de errores por unidad):
  `systemctl show --property=Id,LoadState,ActiveState,SubState,Result,ExecMainStartTimestamp,ExecMainExitTimestamp,ExecMainStatus,LastTriggerUSec,NextElapseUSecRealtime <unit>`
  con entorno `LC_ALL=C`, `TZ=UTC` (copia de `os.environ` con esas dos claves sobrescritas).
- Parsear cada linea `Clave=valor` (partir por el primer `=`).
- Fechas: formato por defecto de systemd con `TZ=UTC` -> `"%a %Y-%m-%d %H:%M:%S %Z"` (comprueba que la zona sea
  `UTC`; si no, `null`). Salida ISO 8601 con zona: `2026-11-13T07:21:48+00:00`. Valores vacios, `n/a`, `0` o no
  parseables -> `null` (sin excepcion: un fallo de parseo no debe tumbar el sensor).
- Funcion de parseo pura y separada (facil de probar).

### D2. Campos publicados por unidad (aditivos)

Los existentes (`name`, `exists`, `load_state`, `active_state`, `sub_state`, `is_active`, `is_failed`,
`status`) **no cambian de nombre ni de significado**. Nuevos:

| Campo | Origen | Notas |
|---|---|---|
| `unit_type` | sufijo del nombre (`service`, `timer`, `socket`...) | siempre |
| `result` | `Result` | cadena o `null` si vacio |
| `last_run_start` | `ExecMainStartTimestamp` | ISO o `null`; solo servicios |
| `last_run_end` | `ExecMainExitTimestamp` | ISO o `null`; solo servicios |
| `last_exit_status` | `ExecMainStatus` | entero; `null` si no hay `last_run_start` o no es servicio |
| `last_trigger` | `LastTriggerUSec` | ISO o `null`; solo timers |
| `next_trigger` | `NextElapseUSecRealtime` | ISO o `null`; solo timers |

Los campos que no aplican al tipo se publican como `null` (forma estable del payload). Las unidades
inexistentes se siguen omitiendo, como hoy.

### D3. Integracion: atributos

`HA4LinuxServiceSensor.extra_state_attributes` anade los siete campos **solo si la clave viene en el
item** (con agentes antiguos no aparecen y no se rompe nada). No cambies `native_value` (sigue siendo
`status`) ni `unique_id`.

### D4. Integracion: entidad de ultima ejecucion (nueva)

Por cada unidad, una entidad `sensor` `device_class: timestamp`, **desactivada por defecto**
(`_attr_entity_registry_enabled_default = False`):

- Valor: `last_trigger` en timers; en servicios `last_run_end`, o `last_run_start` si no hay fin (en curso).
  Parsear la cadena ISO a `datetime` con zona; si falta o no parsea, `None`.
- Nombre: `Service <unit> Last Run`. `unique_id`: `{entry_id}_service_{slug}_last_run`.
- Se crea **solo si el item del agente trae `unit_type`** (agente >= 0.5.17), y se da de alta en el mismo
  bucle dinamico que `HA4LinuxServiceSensor`. Si en un refresco posterior aparece `unit_type` (agente
  actualizado en caliente), la entidad debe crearse sin reiniciar HA: revisa como funciona hoy el alta
  dinamica y ajustala si no lo cubre.
- Atributos opcionales: `result` y `last_exit_status`, para que una automatizacion no necesite la otra
  entidad.
- Traducciones: las entidades de servicio actuales no usan `translation_key` (nombre dinamico). Mantener ese
  patron; si decides usar `translation_key` con placeholders, anade claves `es` y `en` en `strings.json` y
  `translations/`.

### D5. Versiones y compatibilidad

- **Agente 0.5.15 -> 0.5.17** (se salta 0.5.16 para alinearse con la integracion; dilo en el changelog/README).
  Ficheros segun `6c33aac`: `app/main.py` (`API_VERSION`), `config.json`, `packaging/arch/PKGBUILD`,
  `packaging/assets/.../10-ha4linux-managed.conf`, `packaging/assets/sudoers.ha4linux`,
  `packaging/common/install-client.sh`, `packaging/scripts/build-update-bundle.sh` si procede, README.
- Bundle: generar `update-assets/ha4linux-client-update-0.5.17.tar.gz` con
  `packaging/scripts/build-update-bundle.sh` y actualizar `ha4linux/update-manifest.json` (version, URL,
  `sha256` real del fichero generado).
- **Integracion 0.5.16 -> 0.5.17**: `const.py` (`INTEGRATION_VERSION`), `manifest.json`,
  `custom_components/ha4linux/update-manifest.json` (notas).
- `API_SCHEMA_VERSION` se queda en `"1.0"` (cambio aditivo). `API_MIN_INTEGRATION_VERSION` `0.3.0` y
  `API_MAX_INTEGRATION_VERSION` `0.6.x` no cambian: integraciones antiguas ignoran los campos nuevos.
- Compruebas: agente nuevo + integracion 0.5.16 (campos extra ignorados, sin entidades nuevas) e integracion
  nueva + agente 0.5.15 (sin errores, sin entidad de ultima ejecucion).

### D6. Pruebas (`tests/ha4linux/`)

Agente, sin HA (mock de `subprocess.run` y `shutil.which`; cargar `services.py` como hacen las pruebas
existentes, o anadiendo `ha4linux/` al `sys.path`):

- servicio oneshot con exito (`Result=success`, timestamps, `ExecMainStatus=0`);
- servicio con fallo (`ActiveState=failed`, `Result=exit-code`, `ExecMainStatus=1`);
- nunca ejecutado (timestamps vacios, `ExecMainStatus=0` -> `last_exit_status` `null`);
- timer con y sin ultima ejecucion (`LastTriggerUSec=n/a`);
- unidad inexistente (omitida);
- salida en orden distinto al pedido y propiedades ausentes;
- fecha no parseable o en zona distinta de UTC -> `null`;
- que el entorno pasado a `subprocess.run` lleve `LC_ALL=C` y `TZ=UTC`.

Integracion (`test_ha_*.py`, con `pytest-homeassistant-custom-component`):

- payload antiguo (sin campos nuevos): atributos como hoy, sin entidad de ultima ejecucion, sin errores;
- payload nuevo: atributos presentes; entidad timestamp creada desactivada; al activarla, valor correcto para
  timer y para servicio (incluido servicio en curso sin `last_run_end`);
- payload que pasa de antiguo a nuevo entre refrescos (si D4 lo soporta).

Linters: no hay `ruff` instalado ni configuracion en el repo; si puedes, ejecuta `ruff check` sobre los
ficheros tocados (p. ej. `uvx ruff` o `pipx run ruff`) y deja limpios los avisos que introduzcas.

### D7. Documentacion

- `ha4linux/README.md`, seccion del sensor `services`: campos nuevos, que conserva systemd y que no (GC,
  `daemon-reload`, reinicio; `Persistent=true` en timers; efecto de `systemctl reset-failed` sobre `Result`,
  verificado en la prueba funcional), y ejemplo generico de latido en HA, por ejemplo:

  ```yaml
  template:
    - binary_sensor:
        - name: "Backup heartbeat overdue"
          state: >
            {% set t = state_attr('sensor.myhost_service_backup_timer', 'last_trigger') %}
            {{ t is none or (now() - as_datetime(t)) > timedelta(days=3) }}
  ```

  y el equivalente con la entidad de ultima ejecucion activada (`device_class: timestamp`).
- `ha4linux/docs/HA_INTEGRATION.md`: atributos y entidad nuevos.

## Resoluciones de la revision de gaps (fase 1 de Codex)

Prevalecen sobre D1-D7 donde los contradigan.

1. **Alta dinamica.** Llevar registros separados (`known_services` para el sensor de estado y otro para Last
   Run) en `async_setup_entry`, de modo que la entidad Last Run se cree en el refresco en que aparezca
   `unit_type`. Prueba de transicion de payload antiguo a nuevo obligatoria.
2. **Semantica.** `last_trigger` es el **ultimo disparo** del timer, no una ejecucion completada con exito;
   documentarlo asi. El `Result` de un timer es el del propio timer y no dice nada del servicio: la entidad
   Last Run de un timer **no** lleva atributos `result`/`last_exit_status` (en el sensor de estado siguen
   publicandose tal cual). Recuperar fallos historicos cuando systemd ya ha perdido el estado queda **fuera de
   alcance**; documentar que una unidad en `failed` permanece cargada hasta `reset-failed`, asi que la deteccion
   de fallos con `result`/`active_state` es fiable mientras nadie la resetee.
3. **Alcance de Last Run.** Solo para `unit_type` `service` y `timer`. Otros tipos publican `unit_type` y
   `result` en el payload, pero no tienen entidad Last Run.
4. **Versionado del agente.** El commit `6c33aac` es un inventario, no una lista obligatoria. Cambiar solo los
   ficheros que contienen la cadena de version del agente (localizalos con `grep -rn "0\.5\.15" ha4linux/`,
   excluyendo `update-assets/` y documentacion historica) y los que esta funcion requiera; no tocar sudoers,
   instalador ni drop-in si no hace falta (`systemctl show` no requiere privilegios).
5. **Bundle.** `build-update-bundle.sh` empaqueta `app`, `tray`, `icon.png`, `requirements.txt`,
   `packaging/assets` y scripts de instalacion. Generarlo **al final**, tras todos los cambios del agente, y
   anotar en `ha4linux/update-manifest.json` el SHA-256 del fichero final.
6. **Importacion en pruebas.** Pruebas del agente sin HA: anadir `ha4linux/` a `sys.path` en el propio fichero
   de prueba e importar `from app.sensors.services import ServicesSensor`; no depender de `conftest.py`.
7. **Alcance del payload.** Afecta a `/v1/sensors` y a las entidades de HA; la bandeja (`/v1/tray/status`) no
   cambia. Indicarlo en la documentacion.

## Validacion funcional (no la hace Codex)

Codex no tiene un host de pruebas: se queda en pruebas unitarias y, como mucho, una ejecucion **de solo
lectura** de `ServicesSensor.collect()` contra unidades ya existentes de esta maquina (sin `sudo`, sin crear
ni modificar unidades). La prueba con un `oneshot` + timer real (exito, fallo, `reset-failed`) la hacen
despues el usuario y Claude en un host de pruebas.

## Definicion de terminado (para Codex)

- [ ] Informe de gaps entregado y resuelto antes de implementar.
- [ ] D1-D7 implementados en la rama, sin commit.
- [ ] `pytest` en verde (indica si las pruebas `test_ha_*` se ejecutaron o se omitieron por falta de
      dependencias).
- [ ] Sin datos de ninguna instalacion concreta (`git diff` revisado).
- [ ] Resumen final: ficheros tocados, decisiones tomadas en puntos no cubiertos aqui, y pendientes.
