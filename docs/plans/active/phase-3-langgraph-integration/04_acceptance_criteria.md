# Acceptance Criteria — Phase 3

Todos los criterios comienzan en `pending`.

- `AC-P3-001`: `langgraph>=1.2,<2` está sólo en los extras `langgraph` y `all`, y el lock es
  reproducible. Requisitos: `P3-REQ-001`. Tarea: `P3-TASK-0001`.
- `AC-P3-002`: Un artefacto base sin el extra importa y ejecuta contratos core/provider sin
  cargar LangGraph. Requisitos: `P3-REQ-001`, `P3-REQ-018`. Tareas: `P3-TASK-0001`,
  `P3-TASK-0006`.
- `AC-P3-003`: Importar la integración sin el extra falla con una instrucción que nombra
  `proteo-runtime[langgraph]`. Requisitos: `P3-REQ-001`, `P3-REQ-002`. Tarea: `P3-TASK-0001`.
- `AC-P3-004`: `RuntimeNode` es el único export nuevo y core/testing conservan sus límites de
  importación. Requisitos: `P3-REQ-002`, `P3-REQ-003`. Tareas: `P3-TASK-0001`,
  `P3-TASK-0006`.
- `AC-P3-005`: Las claves default consumen `state["input"]` y devuelven sólo
  `{"output": result.value}`. Requisitos: `P3-REQ-004`, `P3-REQ-007`. Tareas:
  `P3-TASK-0002`, `P3-TASK-0006`.
- `AC-P3-006`: Claves y mappers custom funcionan con TypedDict/mappings y el update no conserva
  aliases mutables. Requisitos: `P3-REQ-004`, `P3-REQ-005`. Tareas: `P3-TASK-0002`,
  `P3-TASK-0006`.
- `AC-P3-007`: Key ausente, input inválido y output mapper no-mapping fallan antes de producir un
  update ambiguo. Requisitos: `P3-REQ-004`, `P3-REQ-005`. Tareas: `P3-TASK-0002`,
  `P3-TASK-0006`.
- `AC-P3-008`: Un modelo Pydantic y uno JSON Schema ya enlazados producen valores validados sin
  schema logic adicional en el adaptador. Requisitos: `P3-REQ-006`. Tareas: `P3-TASK-0002`,
  `P3-TASK-0006`.
- `AC-P3-009`: El estado default no contiene objetos runtime/provider, raw ni descriptors.
  Requisitos: `P3-REQ-007`. Tareas: `P3-TASK-0002`, `P3-TASK-0006`.
- `AC-P3-010`: Metadata Proteo y correlación LangGraph permitida llegan a la invocación con el
  shape documentado. Requisitos: `P3-REQ-008`, `P3-REQ-009`. Tareas: `P3-TASK-0003`,
  `P3-TASK-0006`.
- `AC-P3-011`: Claves secret-shaped, valores no JSON y floats no finitos fallan antes del runtime.
  Requisitos: `P3-REQ-010`. Tareas: `P3-TASK-0003`, `P3-TASK-0006`.
- `AC-P3-012`: El `RunnableConfig` original no cambia y callbacks, unknown configurables y el
  descriptor no se filtran a metadata. Requisitos: `P3-REQ-008`, `P3-REQ-009`, `P3-REQ-010`. Tareas:
  `P3-TASK-0003`, `P3-TASK-0006`.
- `AC-P3-013`: Cada RuntimeEvent se emite una vez, en orden, como envelope v1 serializable por
  `json.dumps`. Requisitos: `P3-REQ-011`, `P3-REQ-012`. Tareas: `P3-TASK-0004`,
  `P3-TASK-0006`.
- `AC-P3-014`: El envelope incluye los campos neutrales documentados, usa
  `session_correlation_id` hasheado y nunca contiene el descriptor, result value/raw,
  label/metadata de identidad o SDK objects. Requisitos: `P3-REQ-012`. Tareas:
  `P3-TASK-0004`, `P3-TASK-0006`.
- `AC-P3-015`: Exactamente un terminal exitoso determina el update final y no se duplica en el
  stream. Requisitos: `P3-REQ-013`. Tareas: `P3-TASK-0004`, `P3-TASK-0006`.
- `AC-P3-016`: EOF sin result, completed sin result y terminal exitoso duplicado fallan con error
  neutral seguro. Requisitos: `P3-REQ-013`, `P3-REQ-017`. Tareas: `P3-TASK-0004`,
  `P3-TASK-0006`.
- `AC-P3-017`: Cancelar el task cierra el iterator, activa la interrupción del turno, no duplica
  `session.interrupt()` y vuelve a lanzar `asyncio.CancelledError`. Requisitos: `P3-REQ-014`.
  Tareas: `P3-TASK-0004`, `P3-TASK-0006`.
- `AC-P3-018`: Ningún background task o handle transitorio queda activo tras success, failure,
  mapper error, stream abandonment o cancellation. Requisitos: `P3-REQ-014`, `P3-REQ-016`.
  Tareas: `P3-TASK-0004`–`P3-TASK-0006`.
- `AC-P3-019`: Session mode sin descriptor string no vacío falla antes de resume/provider access.
  Requisitos: `P3-REQ-015`. Tareas: `P3-TASK-0005`, `P3-TASK-0006`.
- `AC-P3-020`: Un descriptor válido reanuda exactamente una sesión, ejecuta un turno y cierra el
  handle una vez conservando historia. Requisitos: `P3-REQ-016`. Tareas: `P3-TASK-0005`,
  `P3-TASK-0006`.
- `AC-P3-021`: Model mode rechaza un descriptor y ningún flujo llama create/archive/delete/migrate
  ni escribe el ID al estado/stream automáticamente. Requisitos: `P3-REQ-015`, `P3-REQ-016`,
  `P3-REQ-017`.
  Tareas: `P3-TASK-0005`, `P3-TASK-0006`.
- `AC-P3-022`: La suite default usa fakes, no lee credenciales, no abre red y mantiene cobertura
  branch-aware mínima de 90 %. Requisitos: `P3-REQ-018`. Tareas: `P3-TASK-0006`,
  `P3-TASK-0008`.
- `AC-P3-023`: Un StateGraph probado demuestra brain, structured, custom stream y sesión
  precreada; el smoke Codex equivalente permanece marcado y opt-in y cada inferencia real afirma
  Luna/low. Requisitos: `P3-REQ-019`, `P3-REQ-021`.
  Tareas: `P3-TASK-0007`, `P3-TASK-0008`.
- `AC-P3-024`: README, ejemplo, versión `0.4.0`, lock, wheel y sdist describen y contienen sólo la
  superficie acordada. Requisitos: `P3-REQ-019`, `P3-REQ-020`. Tareas: `P3-TASK-0007`,
  `P3-TASK-0008`.
- `AC-P3-025`: Ruff, mypy, import-linter, pre-commit, tests, build, installs aisladas y CI
  Linux/Windows Python 3.11–3.14 pasan antes del cierre. Requisitos: `P3-REQ-020`. Tarea:
  `P3-TASK-0008`.
- `AC-P3-026`: Los smokes de inferencia Codex real ejecutan sólo `gpt-5.6-luna` con esfuerzo
  `low`, y cualquier otro modelo observado pertenece a una comprobación sin inferencia. Requisitos:
  `P3-REQ-021`. Tareas: `P3-TASK-0007`, `P3-TASK-0008`.

## Estado de aceptación

`AC-P3-001`–`AC-P3-024` y `AC-P3-026`: `done`, respaldados por la suite local, el ejemplo, los
artefactos 0.4.0 y los smokes opt-in preparados con Luna/low. `AC-P3-025`: `in_progress` hasta
registrar los runs CI Linux/Windows Python 3.11–3.14.
