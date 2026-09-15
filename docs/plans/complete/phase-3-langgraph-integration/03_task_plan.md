# Task Plan — Phase 3

Todas las tareas están cerradas en `done`; cada sección conserva la evidencia de validación
correspondiente.

### P3-TASK-0001 — Crear el límite opcional y la superficie pública

Estado: `done`

Requisitos: `P3-REQ-001`, `P3-REQ-002`, `P3-REQ-003`

Criterios: `AC-P3-001`, `AC-P3-002`, `AC-P3-003`, `AC-P3-004`

Acciones:

- añadir extras `langgraph` y `all`, regenerar el lock y conservar la instalación base;
- crear el paquete de integración y exportar únicamente `RuntimeNode`;
- implementar import error accionable y validación de modo del ejecutor;
- reforzar tests de imports y superficie pública.

Evidencia: `pyproject.toml`, `uv.lock`, `src/proteo_runtime/integrations/langgraph/` y
`tests/contract/test_import_boundaries.py`; `uv lock --check`, import-linter y suite base verdes.

### P3-TASK-0002 — Implementar mapeo de estado y structured nodes

Estado: `done`

Requisitos: `P3-REQ-004`, `P3-REQ-005`, `P3-REQ-006`, `P3-REQ-007`

Criterios: `AC-P3-005`, `AC-P3-006`, `AC-P3-007`, `AC-P3-008`, `AC-P3-009`

Acciones:

- implementar claves default y mappers tipados;
- normalizar entradas exclusivamente por contratos core;
- construir updates copiados y libres de objetos runtime por defecto;
- cubrir texto, RuntimeInput, Pydantic/JSON y fallos de mapper.

Evidencia: `tests/unit/test_langgraph_node.py` y `tests/contract/test_langgraph_adapter.py` cubren
claves, mappers, `RuntimeInput`, Pydantic y ausencia de objetos runtime en el estado.

### P3-TASK-0003 — Propagar configuración y metadata segura

Estado: `done`

Requisitos: `P3-REQ-008`, `P3-REQ-009`, `P3-REQ-010`

Criterios: `AC-P3-010`, `AC-P3-011`, `AC-P3-012`

Acciones:

- mapear namespaces permitidos a un `InvocationConfig` nuevo;
- implementar copia JSON, validación recursiva y rechazo de secretos;
- probar inmutabilidad, allowlist y ausencia del descriptor.

Evidencia: `test_invocation_config_allowlist_and_validation` y
`test_runtime_node_forwards_only_safe_invocation_config` cubren allowlist, copia e inmutabilidad.

### P3-TASK-0004 — Implementar streaming y cancelación

Estado: `done`

Requisitos: `P3-REQ-011`, `P3-REQ-012`, `P3-REQ-013`, `P3-REQ-014`, `P3-REQ-017`

Criterios: `AC-P3-013`, `AC-P3-014`, `AC-P3-015`, `AC-P3-016`, `AC-P3-017`,
`AC-P3-018`

Acciones:

- drenar `astream()` y emitir envelopes JSON v1 al writer custom;
- capturar exactamente un resultado terminal sin serializar su value/raw;
- fallar ante secuencias terminales inválidas;
- cerrar el iterador como única interrupción neutral y restaurar la cancelación original cuando el
  proveedor la normalice como `CancellationError`.

Evidencia: tests unitarios de terminales/EOF, StateGraph `custom` v2 y
`test_runtime_node_restores_task_cancellation_after_provider_normalization`; cobertura branch-aware
local `90.23%`.

### P3-TASK-0005 — Implementar sesiones host-owned

Estado: `done`

Requisitos: `P3-REQ-015`, `P3-REQ-016`, `P3-REQ-017`

Criterios: `AC-P3-019`, `AC-P3-020`, `AC-P3-021`

Acciones:

- validar `configurable.proteo_session_id` antes del runtime;
- reanudar, ejecutar un turno y cerrar el handle en todos los terminales;
- rechazar descriptors en model mode;
- demostrar que no hay create/archive/delete/migrate ni persistencia implícita.

Evidencia: tests de descriptor ausente, reanudación y cierre; contrato StateGraph persistente.

### P3-TASK-0006 — Completar pruebas unitarias y contractuales

Estado: `done`

Requisitos: `P3-REQ-001`, `P3-REQ-004`, `P3-REQ-006`, `P3-REQ-007`, `P3-REQ-008`,
`P3-REQ-010`, `P3-REQ-011`, `P3-REQ-012`, `P3-REQ-013`, `P3-REQ-014`, `P3-REQ-015`,
`P3-REQ-016`, `P3-REQ-017`, `P3-REQ-018`

Criterios: `AC-P3-002`, `AC-P3-004`, `AC-P3-005`, `AC-P3-006`, `AC-P3-007`,
`AC-P3-008`, `AC-P3-009`, `AC-P3-010`, `AC-P3-011`, `AC-P3-012`, `AC-P3-013`,
`AC-P3-014`, `AC-P3-015`, `AC-P3-016`, `AC-P3-017`, `AC-P3-018`, `AC-P3-019`,
`AC-P3-020`, `AC-P3-021`, `AC-P3-022`

Acciones:

- añadir tests focalizados con `FakeRuntime` para cada invariante;
- compilar StateGraphs de texto, structured, stream y sesión;
- probar base install sin extra e integración install con extra;
- mantener el guard de red, credenciales y cuota.

Evidencia: `89 passed, 7 skipped`; tests contractuales con `FakeRuntime`, sin credenciales, red ni
cuota; import-linter conserva el límite core/framework.

### P3-TASK-0007 — Añadir ejemplo y documentación pública

Estado: `done`

Requisitos: `P3-REQ-019`, `P3-REQ-020`, `P3-REQ-021`

Criterios: `AC-P3-023`, `AC-P3-024`, `AC-P3-026`

Acciones:

- añadir un ejemplo StateGraph ejecutable con brain, structured y sesión precreada;
- añadir smoke Codex marcado `integration` y opt-in, forzando `gpt-5.6-luna`/`low` en cada
  inferencia y dejando otros modelos sólo para el test de catálogo;
- documentar instalación, API, streaming custom, ownership y límites de fase;
- actualizar versión pública a `0.4.0` sólo en el workstream de release.

Evidencia: `examples/langgraph_runtime_node.py`, README y smokes `integration` opt-in; toda
inferencia Codex queda fijada a `gpt-5.6-luna`/`low` y el catálogo no invoca modelos.

### P3-TASK-0008 — Validar, entregar y cerrar el SDD

Estado: `done`

Requisitos: `P3-REQ-018`, `P3-REQ-019`, `P3-REQ-020`, `P3-REQ-021`

Criterios: `AC-P3-022`, `AC-P3-023`, `AC-P3-024`, `AC-P3-025`, `AC-P3-026`

Acciones:

- ejecutar gates locales, artefactos e instalaciones aisladas;
- ejecutar la integración Codex sólo con opt-in autorizado;
- publicar commits en inglés y esperar CI Linux/Windows 3.11–3.14;
- registrar evidencia, auditar trazabilidad y mover este mismo paquete a `complete/`.

Evidencia: Ruff, mypy, import-linter, pre-commit, lock, suite con cobertura, artefactos locales y
smokes Codex/LangGraph opt-in (`7 passed`, Luna/low) verdes. CI Linux/Windows Python 3.11–3.14
verde: https://github.com/fernan2cp/proteo-runtime/actions/runs/34982580419.
