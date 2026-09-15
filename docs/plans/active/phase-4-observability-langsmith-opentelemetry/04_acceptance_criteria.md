# Acceptance Criteria — Phase 4

Todos los criterios comienzan en estado `pending`.

- `AC-P4-001`: Metadata de wheel/sdist contiene extras `langsmith`, `otel` y `all` con los rangos
  acordados; OTel SDK queda sólo en desarrollo/test. Requisitos: `P4-REQ-001`. Tareas:
  `P4-TASK-0004`, `P4-TASK-0005`, `P4-TASK-0007`, `P4-TASK-0008`.
- `AC-P4-002`: Una instalación base importa y ejecuta core/Codex sin instalar o cargar LangSmith,
  OpenTelemetry o LangGraph. Requisitos: `P4-REQ-001`, `P4-REQ-012`, `P4-REQ-015`. Tareas:
  `P4-TASK-0004`, `P4-TASK-0005`, `P4-TASK-0007`, `P4-TASK-0008`.
- `AC-P4-003`: El namespace neutral exporta sólo los contratos documentados y conserva los import
  boundaries. Requisitos: `P4-REQ-002`. Tareas: `P4-TASK-0001`, `P4-TASK-0007`.
- `AC-P4-004`: Un observer estructural implementa `on_event/flush/close`; configuración inválida,
  duplicados y timeouts no positivos fallan antes del runtime. Requisitos: `P4-REQ-003`. Tareas:
  `P4-TASK-0001`, `P4-TASK-0007`.
- `AC-P4-005`: Fan-out entrega cada evento una vez por binding, conserva orden causal y continúa
  con observers posteriores tras un fallo no estricto. Requisitos: `P4-REQ-004`, `P4-REQ-010`.
  Tareas: `P4-TASK-0001`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-006`: `ainvoke()` y `astream()` producen la misma secuencia lógica y un solo terminal con
  el mismo resultado/status, sin background tasks. Requisitos: `P4-REQ-004`, `P4-REQ-005`. Tareas:
  `P4-TASK-0001`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-007`: Lifecycle y sesiones emiten los eventos esperados una vez y flush/close idempotentes
  no archivan ni borran historia. Requisitos: `P4-REQ-003`, `P4-REQ-005`. Tareas:
  `P4-TASK-0001`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-008`: Metadata de brain, structured y session contiene todos los campos canónicos
  disponibles y omite limpiamente los desconocidos. Requisitos: `P4-REQ-006`. Tareas:
  `P4-TASK-0002`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-009`: Ambos exporters reciben IDs invocation/session/turn iguales; session correlation es
  estable, namespaced y no permite recuperar ni localizar el descriptor. Requisitos:
  `P4-REQ-007`, `P4-REQ-018`. Tareas: `P4-TASK-0002`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-010`: La matriz de cuatro payload modes cumple exactamente inclusión/exclusión y
  `metadata_only` no contiene texto, output, schema, tools o raw. Requisitos: `P4-REQ-008`. Tareas:
  `P4-TASK-0002`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-011`: `redacted` conserva sólo estructura/marcadores y `full` conserva contenido neutral
  pero elimina secretos, credentials, headers, descriptors y objects provider. Requisitos:
  `P4-REQ-008`, `P4-REQ-009`. Tareas: `P4-TASK-0002`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-012`: Proyectar/redactar no modifica input, event metadata/payload, result, config ni
  colecciones anidadas originales. Requisitos: `P4-REQ-009`. Tareas: `P4-TASK-0002`,
  `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-013`: Un observer fallido deja inferencia exitosa intacta, status `degraded` y diagnostic
  sanitizado único. Requisitos: `P4-REQ-010`. Tareas: `P4-TASK-0001`, `P4-TASK-0003`,
  `P4-TASK-0007`.
- `AC-P4-014`: Strict mode eleva `ObservabilityError` después del fan-out/cleanup; cancelación del
  task conserva `CancelledError`. Requisitos: `P4-REQ-011`. Tareas: `P4-TASK-0001`,
  `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-015`: Status `disabled|healthy|degraded` es observable en runtime/result y fallos de
  dispatch, timeout, flush o close nunca exponen causes/payload. Requisitos: `P4-REQ-010`,
  `P4-REQ-011`. Tareas: `P4-TASK-0001`, `P4-TASK-0003`, `P4-TASK-0007`.
- `AC-P4-016`: Cliente LangSmith falso observa hierarchy runtime→turn→retry/validation/tool y cada
  run termina una sola vez en success/error/interruption/cancellation. Requisitos: `P4-REQ-013`,
  `P4-REQ-014`. Tareas: `P4-TASK-0004`, `P4-TASK-0007`.
- `AC-P4-017`: Un `langgraph_run_id` UUID válido se usa como parent sin importar LangGraph; valor
  ausente/inválido crea una raíz Proteo segura. Requisitos: `P4-REQ-013`. Tareas:
  `P4-TASK-0004`, `P4-TASK-0007`.
- `AC-P4-018`: Import/config sin extra LangSmith nombra `proteo-runtime[langsmith]`; con el extra,
  metadata-only, tags, usage y flush/close funcionan sin payload sensible. Requisitos:
  `P4-REQ-012`, `P4-REQ-014`. Tareas: `P4-TASK-0004`, `P4-TASK-0007`, `P4-TASK-0008`.
- `AC-P4-019`: OTel in-memory contiene spans neutrales anidados con atributos/status/error seguros
  para lifecycle, invocation, turn, retry, validation y tools. Requisitos: `P4-REQ-016`. Tareas:
  `P4-TASK-0005`, `P4-TASK-0007`.
- `AC-P4-020`: Métricas in-memory registran counts/latencia/tokens/retries/tools sólo cuando hay
  datos y nunca usan IDs por invocación como labels. Requisitos: `P4-REQ-016`. Tareas:
  `P4-TASK-0005`, `P4-TASK-0007`.
- `AC-P4-021`: Providers OTel inyectados/globales se usan sin reemplazo ni cierre indebido y el
  import sin extra nombra `proteo-runtime[otel]`. Requisitos: `P4-REQ-015`, `P4-REQ-017`. Tareas:
  `P4-TASK-0005`, `P4-TASK-0007`.
- `AC-P4-022`: Para el mismo evento, LangSmith y OTel contienen exactamente los mismos IDs Proteo
  y campos semánticos comunes, sin assert de `trace_id` compartido. Requisitos: `P4-REQ-018`.
  Tareas: `P4-TASK-0004`, `P4-TASK-0005`, `P4-TASK-0007`.
- `AC-P4-023`: Codex-native OTel no cambia launch config por defecto; opt-in soportado aplica
  configuración antes de startup y opt-in no soportado falla antes de account/model/inference.
  Requisitos: `P4-REQ-019`. Tareas: `P4-TASK-0006`, `P4-TASK-0007`.
- `AC-P4-024`: Codex-native fuerza `log_user_prompt=false`, no acepta/persiste secretos y sólo
  afirma/propaga correlación si upstream la soporta. Requisitos: `P4-REQ-020`. Tareas:
  `P4-TASK-0006`, `P4-TASK-0007`.
- `AC-P4-025`: Exporters y telemetry native no emiten chain-of-thought, hidden reasoning,
  exception causes ni actividad no expuesta. Requisitos: `P4-REQ-021`. Tareas:
  `P4-TASK-0002`, `P4-TASK-0004`–`P4-TASK-0007`.
- `AC-P4-026`: Suite default usa fakes/in-memory, no lee credenciales, no abre red/collector ni
  consume cuota y mantiene cobertura branch-aware ≥90 %. Requisitos: `P4-REQ-022`. Tareas:
  `P4-TASK-0003`, `P4-TASK-0007`, `P4-TASK-0009`.
- `AC-P4-027`: Ejemplo StateGraph produce una traza metadata-only coherente y los smokes externos
  están separados/opt-in; toda inferencia Codex afirma Luna/low. Requisitos: `P4-REQ-024`. Tareas:
  `P4-TASK-0006`, `P4-TASK-0008`, `P4-TASK-0009`.
- `AC-P4-028`: README, versión `0.5.0`, lock, wheel/sdist, instalaciones aisladas, gates locales y
  CI Linux/Windows 3.11–3.14 son consistentes antes del cierre. Requisitos: `P4-REQ-023`. Tareas:
  `P4-TASK-0008`, `P4-TASK-0009`.

## Estado de aceptación

- `AC-P4-001`–`AC-P4-022`: `implemented-local` (ver tests, lint, import boundary y artefactos).
- `AC-P4-023`–`AC-P4-024`: `implemented-local` (capability/config privacy cubierta por dobles;
  smoke Codex-native externo pendiente).
- `AC-P4-025`: `implemented-local` (proyección y canaries de secretos cubiertos por tests).
- `AC-P4-026`: `implemented-local` (suite default segura; `121 passed, 7 skipped` y cobertura
  branch-aware local `90.11%`).
- `AC-P4-027`: `pending` (smokes externos opt-in y evidencia Luna/low no ejecutados).
- `AC-P4-028`: `in_progress` (README, lock, versión y wheel/sdist validados; CI multi-OS pendiente).

El SDD continúa en `active/` hasta que se aporten los smokes/CI pendientes y el propietario
confirme la revisión final; no se moverá a `complete/` automáticamente al terminar este trabajo.
