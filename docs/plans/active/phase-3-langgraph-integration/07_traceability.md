# Traceability — Phase 3

## Guía a requisitos

| Fuente | Requisitos | Tratamiento |
|---|---|---|
| R-002, §5–6, §21 | `P3-REQ-001`–`003` | Extra y adaptador provider-neutral aislado |
| R-003, R-008, §7, §21 | `P3-REQ-004`–`007` | Input/result neutral y structured pass-through |
| R-009, R-027, Phase 3 | `P3-REQ-008`–`010` | Config/metadata allowlisted sin secretos |
| R-019, R-020, §18, Phase 3 | `P3-REQ-011`–`017` | Async stream, cancelación y sesión resume-only |
| R-022, §23–25 | `P3-REQ-018`, `P3-REQ-020` | Fakes, quota safety, extras y calidad |
| §21, §24, Phase 3 exit | `P3-REQ-019` | StateGraph de brain/structured/session sin SDK state |
| R-028, Phase 9 handoff | `P3-REQ-002`, `P3-REQ-020` | Superficie pública explícita y release |
| R-027, integración autorizada | `P3-REQ-021` | Inferencia real restringida a Luna/low |

## Requisitos a tareas, criterios y validación

| Requisito | Tareas | Criterios | Validación |
|---|---|---|---|
| `P3-REQ-001` | `0001`, `0006` | `001`–`004` | extras, base install, import subprocess |
| `P3-REQ-002` | `0001`, `0006` | `003`, `004` | public API e import boundaries |
| `P3-REQ-003` | `0001`, `0006` | `004` | constructor/protocol tests |
| `P3-REQ-004` | `0002`, `0006` | `005`–`007` | default/custom state mapping |
| `P3-REQ-005` | `0002`, `0006` | `006`, `007` | mapper and alias tests |
| `P3-REQ-006` | `0002`, `0006` | `008` | Pydantic/JSON StateGraph tests |
| `P3-REQ-007` | `0002`, `0006` | `005`, `009` | graph-state type inspection |
| `P3-REQ-008` | `0003`, `0006` | `010`, `012` | captured config and immutability |
| `P3-REQ-009` | `0003`, `0006` | `010`, `012` | metadata allowlist matrix |
| `P3-REQ-010` | `0003`, `0006` | `011`, `012` | secret/non-JSON rejection |
| `P3-REQ-011` | `0004`, `0006` | `013` | LangGraph custom stream v2 |
| `P3-REQ-012` | `0004`, `0006` | `013`, `014` | json.dumps and leak assertions |
| `P3-REQ-013` | `0004`, `0006` | `015`, `016` | terminal state-machine tests |
| `P3-REQ-014` | `0004`, `0006` | `017`, `018` | cancellation/aclose/task checks |
| `P3-REQ-015` | `0005`, `0006` | `019`, `021` | missing/invalid/mixed descriptor tests |
| `P3-REQ-016` | `0005`, `0006` | `018`, `020`, `021` | resume/invoke/close spies |
| `P3-REQ-017` | `0004`–`0006` | `016`, `021` | error preservation and mode tests |
| `P3-REQ-018` | `0006`, `0008` | `002`, `022` | quota guard, coverage and default suite |
| `P3-REQ-019` | `0007`, `0008` | `023`, `024` | example plus fake/opt-in execution |
| `P3-REQ-020` | `0007`, `0008` | `024`, `025` | docs, artifacts, local gates and CI |
| `P3-REQ-021` | `0007`, `0008` | `023`, `026` | Luna/low assertions in real inference smokes |

Los números de tarea y criterio en la tabla abrevian `P3-TASK-` y `AC-P3-`.

## Evidencia esperada por criterio

| Criterios | Owner de evidencia |
|---|---|
| `AC-P3-001`–`004` | dependency metadata, isolated imports, public API contracts |
| `AC-P3-005`–`009` | state/input/output/structured unit and StateGraph tests |
| `AC-P3-010`–`012` | captured InvocationConfig and metadata security tests |
| `AC-P3-013`–`018` | JSON stream, terminal, cancellation and cleanup tests |
| `AC-P3-019`–`021` | session resume-only lifecycle tests |
| `AC-P3-022` | quota guard, full suite and coverage report |
| `AC-P3-023`, `AC-P3-026` | executable fake example and authorized Luna/low Codex smoke |
| `AC-P3-024` | README, version, lock, wheel/sdist and isolated installs |
| `AC-P3-025` | local quality gates and final Linux/Windows CI URLs |

## Auditoría mecánica antes del cierre

Extraer todos los IDs `P3-REQ-*`, `P3-TASK-*` y `AC-P3-*` y comprobar:

- cada tarea referencia requisitos y criterios existentes;
- cada requisito aparece en esta matriz, una tarea y un criterio;
- cada criterio referencia requisitos/tareas y tiene owner de evidencia;
- no queda ningún ID pending, in_progress o blocked;
- los comandos y URLs de evidencia están registrados;
- el README público y la guía siguen describiendo el comportamiento implementado;
- el movimiento a `complete/` conserva el nombre del paquete.

## Evidencia registrada en implementación

- `P3-TASK-0001`–`P3-TASK-0007`: `done`; commits `035a988` y `474b03d`, suite focalizada y
  StateGraph contract tests.
- `P3-TASK-0008`: `in_progress`; `uv lock --check`, Ruff, mypy, import-linter, pre-commit,
  `89 passed, 7 skipped`, cobertura `90.23%`, build 0.4.0, checker de artefactos y smokes reales
  opt-in (`7 passed`, Luna/low) verdes; falta únicamente el CI remoto antes de mover el paquete.
- La auditoría de IDs de este documento conserva 21 requisitos, 8 tareas y 26 criterios; no hay
  referencias huérfanas. La evidencia final incorporará las URLs de los runs CI y el commit de
  cierre.

## Regla de control de cambios

Cualquier cambio a la firma de `RuntimeNode`, modos de executor, keys/mappers, metadata allowlist,
envelope JSON, terminal semantics, cancelación, ownership de sesión, rango LangGraph, superficie
pública o target de release debe actualizar requisitos, diseño, tareas, criterios, validación,
rollout y ambas matrices antes de implementarse.
