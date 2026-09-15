# Task Plan — Phase 4

Todas las tareas comienzan en `pending`.

### P4-TASK-0001 — Crear contratos neutrales y event bus

Estado: `done`

Requisitos: `P4-REQ-002`, `P4-REQ-003`, `P4-REQ-004`, `P4-REQ-005`, `P4-REQ-010`,
`P4-REQ-011`

Criterios: `AC-P4-003`, `AC-P4-004`, `AC-P4-005`, `AC-P4-006`, `AC-P4-007`,
`AC-P4-013`, `AC-P4-014`, `AC-P4-015`

Acciones:

- crear el namespace, enums, dataclasses, observer protocol y bus async;
- implementar orden, fan-out, timeouts, lifecycle idempotente y health;
- extender contratos runtime/result y exports del namespace sin contaminar el paquete raíz;
- añadir tests focalizados de protocolo, orden y cierre.

Evidencia: `src/proteo_runtime/observability/`, contratos core y
`tests/unit/test_observability.py`; Ruff, mypy, import-linter y suite local verdes.

### P4-TASK-0002 — Normalizar metadata, correlación y payload redaction

Estado: `done`

Requisitos: `P4-REQ-006`, `P4-REQ-007`, `P4-REQ-008`, `P4-REQ-009`, `P4-REQ-021`

Criterios: `AC-P4-008`, `AC-P4-009`, `AC-P4-010`, `AC-P4-011`, `AC-P4-012`,
`AC-P4-025`

Acciones:

- separar metadata operativa de payload sensible;
- completar metadata terminal y los tres IDs de correlación;
- implementar hash namespaced de descriptor y matriz de payload modes;
- implementar redacción recursiva, copia inmutable y rechazo de objetos no seguros.

Evidencia: payload inmutable, modos/redacción y correlación SHA-256 en
`src/proteo_runtime/observability/bus.py`; matriz unitaria en
`tests/unit/test_observability.py`.

### P4-TASK-0003 — Integrar el bus en runtime, modelos, structured y sesiones

Estado: `done`

Requisitos: `P4-REQ-004`, `P4-REQ-005`, `P4-REQ-006`, `P4-REQ-007`, `P4-REQ-008`,
`P4-REQ-009`, `P4-REQ-010`, `P4-REQ-011`, `P4-REQ-022`

Criterios: `AC-P4-005`, `AC-P4-006`, `AC-P4-007`, `AC-P4-008`, `AC-P4-009`,
`AC-P4-010`, `AC-P4-011`, `AC-P4-012`, `AC-P4-013`, `AC-P4-014`, `AC-P4-015`,
`AC-P4-026`

Acciones:

- conectar lifecycle, `ainvoke()`, `astream()` y operaciones de sesión al bus único;
- asegurar terminal único enriquecido, cancelación y cleanup;
- instrumentar validation/retry sin alterar structured semantics;
- actualizar `FakeRuntime` y contratos runtime-checkable.

Evidencia: bus conectado a Codex `TurnRun`, lifecycle, structured y `FakeRuntime`;
suite final default `121 passed, 7 skipped`, incluyendo invoke, stream, structured y sessions.

### P4-TASK-0004 — Implementar LangSmithObserver

Estado: `done`

Requisitos: `P4-REQ-001`, `P4-REQ-012`, `P4-REQ-013`, `P4-REQ-014`, `P4-REQ-018`,
`P4-REQ-021`

Criterios: `AC-P4-001`, `AC-P4-002`, `AC-P4-016`, `AC-P4-017`, `AC-P4-018`,
`AC-P4-022`, `AC-P4-025`

Acciones:

- añadir extra/import guard y adapter con cliente inyectable;
- mapear hierarchy, terminales, usage, tags y parent LangGraph;
- respetar payload modes y ejecutar operaciones bloqueantes fuera del event loop;
- cubrir cliente falso, flush/close, fallos y runs huérfanos.

Evidencia: `LangSmithObserver` con cliente inyectable, jerarquía y operaciones en
`asyncio.to_thread`; pruebas con cliente falso. Smoke con servicio externo pendiente.

### P4-TASK-0005 — Implementar OpenTelemetryObserver

Estado: `done`

Requisitos: `P4-REQ-001`, `P4-REQ-015`, `P4-REQ-016`, `P4-REQ-017`, `P4-REQ-018`,
`P4-REQ-021`

Criterios: `AC-P4-001`, `AC-P4-002`, `AC-P4-019`, `AC-P4-020`, `AC-P4-021`,
`AC-P4-022`, `AC-P4-025`

Acciones:

- añadir extra/import guard y adapter con providers/instrumentos inyectables;
- mapear spans, status, span events y métricas sin cardinalidad alta;
- respetar ownership de providers y payload/redaction;
- validar con OTel SDK y exporters/readers in-memory.

Evidencia: `OpenTelemetryObserver` con tracer/meter inyectables, spans, métricas y
ownership neutral; fakes e `opentelemetry-sdk==1.44.0` con exporters in-memory pasan localmente.
Smoke OTLP pendiente.

### P4-TASK-0006 — Implementar enriquecimiento Codex-native OTel

Estado: `done`

Requisitos: `P4-REQ-019`, `P4-REQ-020`, `P4-REQ-021`, `P4-REQ-024`

Criterios: `AC-P4-023`, `AC-P4-024`, `AC-P4-025`, `AC-P4-027`

Acciones:

- añadir configuración provider-specific y validación pre-start;
- forzar privacidad default y excluir secretos/headers del contrato Proteo;
- detectar propagación de IDs y exponer capability real sin simular soporte;
- probar equivalencia de inferencia habilitada/deshabilitada y failure paths.

Evidencia: `CodexNativeOtelConfig` y capabilities en `providers/codex/native_otel.py`,
privacidad `log_user_prompt=false` y capability gate antes de startup; smoke nativo pendiente.

### P4-TASK-0007 — Completar pruebas unitarias y contractuales

Estado: `done`

Requisitos: `P4-REQ-001`–`P4-REQ-022`

Criterios: `AC-P4-001`–`AC-P4-026`

Acciones:

- construir matrices de eventos, payload, exporters y errores;
- reforzar import boundaries, quota safety y concurrencia/cancelación;
- probar LangGraph con `FakeRuntime` y ambos exporters in-memory/fake;
- mantener cobertura branch-aware mínima de 90 %.

Evidencia: tests unitarios/contractuales default con fakes e in-memory; `121 passed, 7 skipped`.
La cobertura branch-aware local es `90.11%` y satisface el gate configurado de `90%`; CI
multi-OS sigue pendiente.

### P4-TASK-0008 — Añadir ejemplo, documentación, packaging y release

Estado: `done`

Requisitos: `P4-REQ-001`, `P4-REQ-012`, `P4-REQ-015`, `P4-REQ-023`, `P4-REQ-024`

Criterios: `AC-P4-001`, `AC-P4-002`, `AC-P4-018`, `AC-P4-027`, `AC-P4-028`

Acciones:

- actualizar extras, lock, versión `0.5.0` y artifact checks;
- documentar configuración, privacidad, strict mode y ownership;
- añadir ejemplo StateGraph metadata-only sin credenciales embebidas;
- preparar smokes externos separados, opt-in y Luna/low.

Evidencia: README, ejemplo metadata-only, extras `langsmith`/`otel`/`all`, `uv.lock`,
versión `0.5.0` y artefactos wheel/sdist construidos.

### P4-TASK-0009 — Validar, entregar y cerrar el SDD

Estado: `in_progress`

Requisitos: `P4-REQ-022`–`P4-REQ-024`

Criterios: `AC-P4-026`–`AC-P4-028`

Acciones:

- ejecutar gates locales, artefactos e instalaciones aisladas;
- ejecutar smokes externos sólo con opt-in autorizado;
- publicar commits en inglés y esperar CI Linux/Windows 3.11–3.14;
- registrar evidencia y auditar IDs; el paquete permanecerá en `active/` hasta la revisión
  explícita del propietario, sin moverlo automáticamente a `complete/`.

Evidencia: gates locales Ruff, mypy, import-linter, pre-commit, pytest (121 passed, 7 skipped),
coverage branch-aware 90.11%, build e instalaciones aisladas de wheel/sdist verdes; pendientes
smokes externos, CI remoto Linux/Windows y revisión humana. El SDD permanece deliberadamente en
`active/`.
