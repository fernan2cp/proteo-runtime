# Traceability — Phase 5

## Guía a requisitos

| Fuente | Requisitos | Tratamiento |
|---|---|---|
| §2.1, R-014 | `P5-REQ-005`–`P5-REQ-007`, `P5-REQ-015` | Autoridad y ejecución host-only |
| R-015–R-017, §9, §13 | `P5-REQ-006`, `P5-REQ-012`–`P5-REQ-015` | Profiles, permisos, capabilities y safe defaults |
| §12 Tool definition | `P5-REQ-001`–`P5-REQ-004` | API neutral, schemas y registry |
| §12 execution policy | `P5-REQ-005`–`P5-REQ-011` | Pipeline, HITL, timeout, retry, dedupe y fallos |
| R-010–R-011, R-027, §14–§16 | `P5-REQ-016`, `P5-REQ-017`, `P5-REQ-021` | Eventos, payload, redacción y exporters |
| R-023, R-029, §24, Phase 5 | `P5-REQ-018`–`P5-REQ-021` | Adapter experimental y compatibility boundary |
| R-022, §21–§25 | `P5-REQ-022`–`P5-REQ-024` | Tests, cuota, packaging, smoke, CI y release |

## Requisitos a tareas, criterios y validación

| Requisito | Tareas | Criterios | Validación |
|---|---|---|---|
| `P5-REQ-001` | `0001`, `0007` | `001`, `002` | import boundary, metadata y public API |
| `P5-REQ-002` | `0001`, `0007` | `003` | schema/signature matrix |
| `P5-REQ-003` | `0001`, `0007` | `004` | registry/snapshot isolation |
| `P5-REQ-004` | `0001`, `0007` | `002`, `005` | immutability y JSON safety |
| `P5-REQ-005` | `0002`, `0007` | `006` | executor stage/order matrix |
| `P5-REQ-006` | `0002`, `0007` | `007` | exact permission tests |
| `P5-REQ-007` | `0002`, `0007` | `008`, `009` | approval matrix |
| `P5-REQ-008` | `0002`, `0006`, `0007` | `009`, `010` | timeout/cancel/cleanup tests |
| `P5-REQ-009` | `0002`, `0007` | `011`, `012` | idempotency/retry matrix |
| `P5-REQ-010` | `0002`, `0006`, `0007` | `013` | concurrent duplicate tests |
| `P5-REQ-011` | `0002`, `0007` | `012`, `013` | return-error/raise matrix |
| `P5-REQ-012` | `0003`, `0007` | `014` | model binding/profile tests |
| `P5-REQ-013` | `0003`, `0006`, `0007` | `016`, `017` | session create/resume tests |
| `P5-REQ-014` | `0003`, `0007` | `015` | capability intersection matrix |
| `P5-REQ-015` | `0003`, `0006`, `0007` | `018` | launch/sandbox/native denial spies |
| `P5-REQ-016` | `0004`, `0007` | `019` | event ordering/exact-once tests |
| `P5-REQ-017` | `0004`, `0007` | `020`, `021` | payload/exporter matrices |
| `P5-REQ-018` | `0005`, `0007` | `022` | flag/capability matrix |
| `P5-REQ-019` | `0005`, `0006`, `0007` | `023` | App Server protocol double |
| `P5-REQ-020` | `0005`, `0007` | `024` | compatibility fault injection |
| `P5-REQ-021` | `0004`, `0005`, `0006`, `0007` | `005`, `017`, `020`, `025` | persistence/no-leak canaries |
| `P5-REQ-022` | `0007`, `0009` | `026` | quota guard/full suite/coverage |
| `P5-REQ-023` | `0008`, `0009` | `028` | docs, ADR, artifacts, gates y CI |
| `P5-REQ-024` | `0008`, `0009` | `027` | smoke opt-in Luna/low |

Los números de tarea y criterio en la tabla abrevian `P5-TASK-` y `AC-P5-`.

## Evidencia esperada por criterio

| Criterios | Owner de evidencia |
|---|---|
| `AC-P5-001`–`AC-P5-005` | neutral API, schema/registry tests, import-linter y canaries |
| `AC-P5-006`–`AC-P5-013` | executor, permission, approval, retry, timeout y dedupe tests |
| `AC-P5-014`–`AC-P5-018` | model/session/profile/capability/security contract tests |
| `AC-P5-019`–`AC-P5-021` | event sequence, payload, LangSmith fake y OTel in-memory |
| `AC-P5-022`–`AC-P5-025` | App Server double, fault injection, lifecycle y no-leak tests |
| `AC-P5-026` | quota guard, suite default y reporte coverage |
| `AC-P5-027` | smoke Codex opt-in con evidencia Luna/low sanitizada |
| `AC-P5-028` | ADR/docs/version/lock/artifacts/gates/CI/revisión |

## Auditoría mecánica antes del cierre

Extraer todos los IDs `P5-REQ-*`, `P5-TASK-*` y `AC-P5-*` y comprobar:

- cada tarea referencia requisitos y criterios existentes;
- cada requisito aparece en esta matriz, al menos una tarea y un criterio;
- cada criterio referencia requisitos/tareas y tiene owner de evidencia;
- no queda ningún ID pending, in_progress o blocked;
- comandos, resultados, artifact hashes y URLs CI quedan registrados;
- guía, ADR, README público y SDD describen el mismo comportamiento;
- no hay cambios de código fuera del alcance registrado por las tareas;
- el movimiento a `complete/` conserva el nombre del paquete.

## Estado de implementación y revisión

- Requisitos `P5-REQ-001`–`P5-REQ-024`: `done`.
- Tareas `P5-TASK-0001`–`P5-TASK-0008`: `done`.
- `P5-TASK-0009`: `in_progress — owner review pending`.
- Criterios `AC-P5-001`–`AC-P5-028`: `done`.
- Estado global: `in_progress — owner review pending`.

La evidencia reproducible está en `05_validation_plan.md`, con commits funcionales desde
`900bdd5` hasta `08445fc` y CI remoto `35027524386`. El estado pendiente es deliberado: sólo la
confirmación explícita del propietario permite marcar `P5-TASK-0009` como `done`, actualizar el
estado final y mover esta misma carpeta a `docs/plans/complete/`.

## Regla de control de cambios

Cualquier cambio a symbols, schemas, permission matching, approval defaults, timeout/retry,
idempotencia, failure policy, binding de sesiones, event semantics, payload projection,
capability gating, protocolo Codex, rango SDK o target `0.6.0` debe actualizar requirements,
technical design, tasks, criteria, validation, rollout y ambas matrices antes de implementarse.
