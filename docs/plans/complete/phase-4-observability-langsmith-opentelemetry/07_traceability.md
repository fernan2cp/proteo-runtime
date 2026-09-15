# Traceability — Phase 4

## Guía a requisitos

| Fuente | Requisitos | Tratamiento |
|---|---|---|
| §2.4, R-010, Phase 4 | `P4-REQ-004`–`P4-REQ-007` | Bus observable, metadata e IDs |
| R-011, §14 | `P4-REQ-002`–`P4-REQ-005`, `P4-REQ-010`, `P4-REQ-011` | Contratos neutrales, orden y fallos |
| R-010, §15 LangSmith | `P4-REQ-012`–`P4-REQ-014` | Observer oficial y hierarchy |
| R-011, §15 OTel | `P4-REQ-015`–`P4-REQ-018` | Spans, métricas y correlación |
| R-011, Phase 4 native | `P4-REQ-019`, `P4-REQ-020` | Enriquecimiento Codex opt-in |
| R-027, §15 payloads | `P4-REQ-008`, `P4-REQ-009`, `P4-REQ-020`, `P4-REQ-021` | Redacción, secretos y límites de visibilidad |
| R-022, §23–25 | `P4-REQ-001`, `P4-REQ-022`–`P4-REQ-024` | Extras, quota safety, release y CI |

## Requisitos a tareas, criterios y validación

| Requisito | Tareas | Criterios | Validación |
|---|---|---|---|
| `P4-REQ-001` | `0004`, `0005`, `0007`, `0008` | `001`, `002` | metadata, imports e installs aisladas |
| `P4-REQ-002` | `0001`, `0007` | `003` | public API e import-linter |
| `P4-REQ-003` | `0001`, `0007` | `004`, `007` | protocol/lifecycle tests |
| `P4-REQ-004` | `0001`, `0003`, `0007` | `005`, `006` | fan-out/order/exact-once |
| `P4-REQ-005` | `0001`, `0003`, `0007` | `006`, `007` | invoke/stream/session matrices |
| `P4-REQ-006` | `0002`, `0003`, `0007` | `008` | metadata matrix |
| `P4-REQ-007` | `0002`, `0003`, `0007` | `009` | correlation/hash/leak tests |
| `P4-REQ-008` | `0002`, `0003`, `0007` | `010`, `011` | payload mode matrix |
| `P4-REQ-009` | `0002`, `0003`, `0007` | `011`, `012` | canaries e inmutabilidad |
| `P4-REQ-010` | `0001`, `0003`, `0007` | `005`, `013`, `015` | observer failure/status/diagnostic |
| `P4-REQ-011` | `0001`, `0003`, `0007` | `014`, `015` | strict/cancel/cleanup tests |
| `P4-REQ-012` | `0004`, `0007`, `0008` | `002`, `018` | optional import/client fake |
| `P4-REQ-013` | `0004`, `0007` | `016`, `017` | run tree y LangGraph parent |
| `P4-REQ-014` | `0004`, `0007` | `016`, `018` | terminal/metadata/flush tests |
| `P4-REQ-015` | `0005`, `0007`, `0008` | `002`, `021` | optional import/extra tests |
| `P4-REQ-016` | `0005`, `0007` | `019`, `020` | OTel in-memory spans/metrics |
| `P4-REQ-017` | `0005`, `0007` | `021` | provider ownership tests |
| `P4-REQ-018` | `0004`, `0005`, `0007` | `009`, `022` | cross-exporter equality |
| `P4-REQ-019` | `0006`, `0007` | `023` | launch/capability spies |
| `P4-REQ-020` | `0006`, `0007` | `024` | config privacy/correlation tests |
| `P4-REQ-021` | `0002`, `0004`–`0007` | `025` | leak/hidden-activity assertions |
| `P4-REQ-022` | `0003`, `0007`, `0009` | `026` | quota guard/full suite/coverage |
| `P4-REQ-023` | `0008`, `0009` | `028` | docs/artifacts/gates/CI |
| `P4-REQ-024` | `0006`, `0008`, `0009` | `027` | opt-in smokes y Luna/low |

Los números de tarea y criterio en la tabla abrevian `P4-TASK-` y `AC-P4-`.

## Evidencia esperada por criterio

| Criterios | Owner de evidencia |
|---|---|
| `AC-P4-001`, `AC-P4-002` | artifact metadata, subprocess imports e installs aisladas |
| `AC-P4-003`–`AC-P4-007` | neutral contracts, event bus y lifecycle unit/contract tests |
| `AC-P4-008`–`AC-P4-012` | metadata, payload, redaction, correlation e immutability matrices |
| `AC-P4-013`–`AC-P4-015` | failure, timeout, strict, cancellation, status y diagnostics tests |
| `AC-P4-016`–`AC-P4-018` | LangSmith fake client y StateGraph parent contract |
| `AC-P4-019`–`AC-P4-021` | OTel SDK in-memory spans, metrics y ownership tests |
| `AC-P4-022` | dual-exporter correlation contract |
| `AC-P4-023`, `AC-P4-024` | Codex launch spies y smoke native opt-in |
| `AC-P4-025` | secret/hidden-reasoning canary scan |
| `AC-P4-026` | quota guard, suite default y coverage report |
| `AC-P4-027` | ejemplo StateGraph y smokes externos autorizados |
| `AC-P4-028` | docs, version, lock, artifacts, gates y CI final |

## Auditoría mecánica antes del cierre

Extraer todos los IDs `P4-REQ-*`, `P4-TASK-*` y `AC-P4-*` y comprobar:

- cada tarea referencia requisitos y criterios existentes;
- cada requisito aparece en esta matriz, al menos una tarea y un criterio;
- cada criterio referencia requisitos/tareas y tiene owner de evidencia;
- no queda ningún ID pending, in_progress o blocked;
- comandos, resultados y URLs CI quedan registrados;
- guía, README público y SDD describen el mismo comportamiento;
- el movimiento a `complete/` conserva el nombre del paquete.

## Estado actual (tras implementación local)

- Requisitos `P4-REQ-001`–`P4-REQ-022`: `implemented-local`; `P4-REQ-023`:
  `in_progress`; `P4-REQ-024`: `pending` por smokes externos.
- Tareas `P4-TASK-0001`–`P4-TASK-0008`: `done`; `P4-TASK-0009`: `in_progress` por CI,
  smokes y revisión.
- Criterios `AC-P4-001`–`AC-P4-026`: `implemented-local`; `AC-P4-028`:
  `in_progress`; `AC-P4-027`: `pending` por smokes externos.

Evidencia local: `121 passed, 7 skipped` (incluye OTel SDK in-memory), Ruff, mypy, import-linter,
pre-commit y build de wheel/sdist verdes. Cobertura branch-aware medida: `90.11%` (gate objetivo
`≥90%`). El paquete
permanece deliberadamente en `active/` hasta completar evidencia externa/CI y la revisión del
propietario; no se moverá a `complete/` sin su confirmación explícita.

## Regla de control de cambios

Cualquier cambio a la superficie neutral, orden/terminal semantics, payload modes, redacción,
correlación, failure policy, hierarchy, ownership OTel, configuración Codex-native, rangos de
extras o target `0.5.0` debe actualizar requisitos, diseño, tareas, criterios, validación, rollout y
ambas matrices antes de implementarse.
