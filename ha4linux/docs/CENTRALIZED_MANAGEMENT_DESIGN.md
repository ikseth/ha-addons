# Diseno Tecnico: Gestion centralizada de APIs ha4linux desde Home Assistant

## 1. Objetivo
Disponer de un modelo centralizado donde Home Assistant:
- Detecte version y compatibilidad de cada API ha4linux remota.
- Avise de desactualizacion y drift de configuracion.
- Orqueste acciones de actualizacion y configuracion.

Manteniendo el enfoque recomendado:
- La actualizacion se ejecuta localmente en cada host API (self-update).
- HA coordina y supervisa, no hace despliegues ad-hoc por SSH de forma directa.

## 2. Principios de arquitectura
1. Escalabilidad: N hosts gestionados con el mismo contrato API.
2. Resiliencia: cada host puede actualizarse de forma autonoma y recuperarse.
3. Modularidad: update/config como modulos separados del core de sensores.
4. Seguridad por defecto: update/config remotos desactivados salvo habilitacion explicita.

## 3. Componentes

### 3.1 En cada host Linux (API)
- `ha4linux.service` (API principal).
- Worker transitorio de actualizacion lanzado con `systemd-run` fuera del sandbox de `ha4linux.service`.
- `ha4linux-update.timer` (comprobacion periodica opcional).
- `ha4linux-agent` (modulo software en la API) con:
  - chequeo de version objetivo,
  - descarga de artefacto firmado,
  - validacion de firma/hash,
  - aplicacion atomica,
  - restart controlado,
  - rollback local si health falla.

### 3.2 En Home Assistant
- Integracion `custom_components/ha4linux` ampliada con:
  - sensores de version/compatibilidad,
  - entidad `update` por host,
  - botones/acciones de mantenimiento (check/apply/schedule/cancel),
  - switches o selects de configuracion declarativa (si host lo permite).

## 4. Contrato API propuesto

## 4.1 Versionado y compatibilidad
- `GET /v1/version`
  - `api_version`: version semantica binaria
  - `schema_version`: version de contrato
  - `min_integration_version`
  - `max_integration_version`
  - `build` (commit/date/channel)

Ejemplo:
```json
{
  "api_version": "0.4.0",
  "schema_version": "2.0",
  "min_integration_version": "0.3.0",
  "max_integration_version": "0.5.x",
  "build": {
    "commit": "69a96ca",
    "date": "2026-03-11T08:00:00Z",
    "channel": "stable"
  }
}
```

## 4.2 Estado de actualizacion
- `GET /v1/update/status`
- `POST /v1/update/check`
- `POST /v1/update/apply`
- `POST /v1/update/rollback`

`status` debe incluir:
- `installed_version`, `target_version`, `update_available`
- `state` (`idle|checking|downloading|applying|restarting|rollback|error`)
- `last_error`, `last_checked_at`, `last_applied_at`
- `pending_reboot` si aplica

## 4.3 Configuracion remota declarativa
- `GET /v1/config/effective`
- `GET /v1/config/schema`
- `POST /v1/config/validate`
- `POST /v1/config/apply`

Secciones iniciales de configuracion:
- `modules`: enable/disable (`services`, `virtualbox`, `raid_mdstat`, etc.)
- `services.watchlist`
- `app_policies.apps`
- `readonly_mode`

Aplicacion segura:
- validacion previa,
- persistencia atomica,
- `restart_required` + ventana de aplicacion.

## 5. Seguridad
1. Token con scopes:
   - `read:sensors`, `read:version`, `write:update`, `write:config`.
2. Flags de seguridad por host (default `false`):
   - `HA4LINUX_REMOTE_UPDATE_ENABLED`
   - `HA4LINUX_REMOTE_CONFIG_ENABLED`
3. Verificacion de artefactos:
   - firma (GPG/cosign) + `sha256`.
4. Auditoria:
   - log estructurado de operaciones remotas (`who`, `when`, `what`, `result`).
5. Guardas operativas:
   - denegar update si `readonly_mode=true` y politica lo exige,
   - ventana de mantenimiento opcional.

## 6. Modelo de actualizacion recomendado (self-update)
1. HA ejecuta `POST /v1/update/check`.
2. API compara con feed de releases (GitHub Release o repo interno).
3. Si hay nueva version compatible, HA muestra entidad `update`.
4. HA lanza `POST /v1/update/apply`.
5. Host descarga artefacto, valida firma/hash, instala, reinicia servicio.
6. Health-check post-update:
   - `GET /health`
   - `GET /v1/version`
   - `GET /v1/capabilities`
7. Si falla, rollback local a version previa y notificacion de error.

Notas de implementacion:
- La API no debe intentar autoactualizarse dentro de su propio sandbox `systemd`.
- La unidad base `ha4linux.service` debe mantenerse estable; los cambios evolutivos deben ir en `drop-ins` gestionados para evitar reescrituras fragiles del unit principal.
- `POST /v1/update/apply` debe pasar por un `preflight` explicito antes de ofrecer o ejecutar la actualizacion.

## 7. Modelo de configuracion desde HA
Caso Kodi:
- En lugar de hardcode, HA gestiona `app_policies.apps`.
- Si `apps=[]`, no se crean switches de app policy.
- Para desactivar solo Kodi:
  - eliminar entrada `id=kodi` de `apps` y aplicar.

Caso modulos:
- Activar/desactivar `services`, `virtualbox`, etc. via config declarativa.
- HA refresca entidades en base a capacidades efectivas.

## 8. Entidades HA propuestas
Por cada host:
- `sensor.ha4linux_<host>_api_version`
- `sensor.ha4linux_<host>_schema_version`
- `binary_sensor.ha4linux_<host>_api_compatible`
- `update.ha4linux_<host>_api`
- `sensor.ha4linux_<host>_update_state`
- `button.ha4linux_<host>_check_update`
- `button.ha4linux_<host>_apply_update`
- `button.ha4linux_<host>_rollback_update`

Opcional (si config remota habilitada):
- `switch.ha4linux_<host>_module_services`
- `switch.ha4linux_<host>_module_virtualbox`
- `select.ha4linux_<host>_maintenance_window`

## 9. Plan de implementacion por fases

### Fase 1 (base, bajo riesgo)
- Endpoint `/v1/version`.
- Sensores HA de version/compatibilidad.
- Deteccion de drift y alerta visual.

### Fase 2 (update autonoma)
- `ha4linux-update.service/timer`.
- Endpoints `/v1/update/*`.
- Entidad `update` en HA + acciones check/apply.

### Fase 3 (config declarativa)
- Endpoints `/v1/config/*` con schema/validate/apply.
- UI en HA para modulos y politicas de apps.

### Fase 4 (hardening)
- scopes finos, auditoria completa, politicas de ventana, canary rollout por grupos.

## 10. Riesgos y mitigaciones
1. Riesgo: update rompe contrato de integracion.
   Mitigacion: `schema_version` + matriz de compatibilidad + bloqueo preventivo.
2. Riesgo: host inaccesible durante update.
   Mitigacion: worker local con rollback automatico y timeout.
3. Riesgo: cambios remotos no autorizados.
   Mitigacion: scopes, flags de habilitacion, auditoria y secrets rotables.

## 11. Criterios de exito
1. HA detecta de forma fiable APIs desactualizadas/compatibles.
2. Update remota funciona sin SSH ad-hoc y con rollback automatico.
3. Configuracion declarativa (incluyendo politicas tipo Kodi) gestionable desde HA con trazabilidad.
