# Evaluacion: limitacion modular de aplicaciones (Kodi y otras)

## Viabilidad

Es factible y encaja con el modelo actual de modulos (`core + sensores + actuadores`).

## Enfoque recomendado (generico)

Crear un nuevo modulo de politica de aplicaciones, no especifico de Kodi:

- Sensor de politica por aplicacion (`allowed` / `blocked` / `running` / `violating`).
- Actuador de politica (`allow`, `block`, `enforce_now`).
- Configuracion por fichero de politicas en el cliente Linux.

## Archivo de politicas propuesto

Ruta: `/etc/ha4linux/policies/apps.yaml`

Ejemplo:

```yaml
apps:
  - id: kodi
    match:
      process_names: ["kodi.bin", "kodi"]
      service_names: ["kodi.service"]
    policy:
      mode: schedule
      allow:
        - days: [mon, tue, wed, thu, fri]
          from: "18:00"
          to: "20:00"
        - days: [sat, sun]
          from: "10:00"
          to: "22:00"
    enforcement:
      on_violation: terminate
      cooldown_seconds: 30

  - id: steam
    match:
      process_names: ["steam"]
    policy:
      mode: always_block
    enforcement:
      on_violation: terminate
```

## Mecanismo de enforcement (MVP robusto)

1. Deteccion de procesos por `process_names`.
2. Evaluacion de politica temporal.
3. Si viola politica:
   - `terminate` proceso detectado (graceful y luego forzado opcional).
4. Reporte de estado y ultimo evento para HA.

## Entidades HA previstas

Por cada app definida:

- `binary_sensor.<app>_running`
- `binary_sensor.<app>_policy_violation`
- `switch.<app>_allowed` (ON permite, OFF bloquea)
- `sensor.<app>_next_window` (opcional)

## Riesgos y mitigaciones

- Falsos positivos por nombre de proceso:
  - Mitigar con multiples criterios (`process`, `service`, uid).
- Evasion por renombrado de binario:
  - Mitigar con hashes/rutas firmes en fase 2.
- Impacto en UX:
  - Modo observacion inicial (`monitor_only`) antes de bloquear.

## Plan por fases

1. Fase 1 (MVP): `monitor_only` + `terminate` por proceso.
2. Fase 2: ventanas horarias avanzadas, excepciones y cooldowns.
3. Fase 3: perfiles por usuario/menor y plantillas ("Google Family-like").

## Conclusion

La funcionalidad es viable y recomendable si se implementa como modulo generico de politicas,
con configuracion declarativa y arranque en modo observacion antes de enforcement.
