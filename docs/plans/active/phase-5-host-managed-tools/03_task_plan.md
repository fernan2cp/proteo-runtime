# Task Plan — Phase 5

Todas las tareas comienzan en `pending`.

### P5-TASK-0001 — Crear contratos neutrales, schemas y registry

Estado: `done`

Requisitos: `P5-REQ-001`, `P5-REQ-002`, `P5-REQ-003`, `P5-REQ-004`

Criterios: `AC-P5-001`, `AC-P5-002`, `AC-P5-003`, `AC-P5-004`, `AC-P5-005`

Acciones:

- crear namespace, enums, dataclasses, protocols y exports explícitos;
- implementar decorator async y generación/validación de schemas;
- implementar registry determinista y snapshots inmutables;
- añadir tests focalizados de contratos, firmas y JSON safety.

Evidencia: `900bdd5`, `tests/unit/test_host_tools.py` (schemas, firmas, registry, snapshots y
JSON safety).

### P5-TASK-0002 — Implementar permisos, aprobación y ToolExecutor

Estado: `done`

Requisitos: `P5-REQ-005`, `P5-REQ-006`, `P5-REQ-007`, `P5-REQ-008`, `P5-REQ-009`,
`P5-REQ-010`, `P5-REQ-011`

Criterios: `AC-P5-006`–`AC-P5-013`

Acciones:

- implementar pipeline fijo de resolución, validación y autorización;
- añadir ApprovalHandler fail-closed y timeouts por etapa;
- añadir retries idempotentes, deduplicación y cleanup por invocación;
- implementar return-error/raise con errores y resultados sanitizados.

Evidencia: `900bdd5`, `tests/unit/test_host_tools.py` (permisos, aprobación fail-closed,
timeouts, retries, deduplicación y políticas de fallo).

### P5-TASK-0003 — Integrar bindings, profiles, capabilities y fakes

Estado: `done`

Requisitos: `P5-REQ-012`, `P5-REQ-013`, `P5-REQ-014`, `P5-REQ-015`

Criterios: `AC-P5-014`–`AC-P5-018`

Acciones:

- añadir `with_tools()` inmutable al protocolo/modelos/fakes;
- extender factories de sesión y resume con binding explícito;
- calcular provider/effective capabilities sin expansión de permisos;
- conservar rechazo pre-inference en perfiles incompatibles.

Evidencia: `b4f0c14`, `f747468` (bindings inmutables, perfiles, capacidades, sesiones y fakes).

### P5-TASK-0004 — Completar eventos y observabilidad de tools

Estado: `done`

Requisitos: `P5-REQ-016`, `P5-REQ-017`, `P5-REQ-021`

Criterios: `AC-P5-019`, `AC-P5-020`, `AC-P5-021`, `AC-P5-025`

Acciones:

- agregar event kinds y metadata/payload canónicos;
- emitir orden causal exact-once desde executor y runtime;
- actualizar redacción, LangSmith y OpenTelemetry;
- cubrir terminales, retries, denegaciones y no-leak canaries.

Evidencia: `5300776`, `f747468` (eventos, redacción y exporters LangSmith/OpenTelemetry).

### P5-TASK-0005 — Implementar adapter experimental Codex

Estado: `done`

Requisitos: `P5-REQ-018`, `P5-REQ-019`, `P5-REQ-020`, `P5-REQ-021`

Criterios: `AC-P5-022`, `AC-P5-023`, `AC-P5-024`, `AC-P5-025`

Acciones:

- añadir feature flag y capability handshake;
- serializar dynamicTools y manejar `item/tool/call` en shim privado;
- reconciliar lifecycle provider con eventos/resultados neutrales;
- fallar cerrado ante versiones, fields, methods o hooks incompatibles.

Evidencia: `b99131c`, `f747468` y smoke opt-in (probe, feature flag, dynamicTools y bridge privado).

### P5-TASK-0006 — Integrar lifecycle, sesiones y cancelación Codex

Estado: `done`

Requisitos: `P5-REQ-008`, `P5-REQ-010`, `P5-REQ-013`, `P5-REQ-015`, `P5-REQ-019`,
`P5-REQ-021`

Criterios: `AC-P5-010`, `AC-P5-013`, `AC-P5-016`, `AC-P5-017`, `AC-P5-018`,
`AC-P5-023`, `AC-P5-025`

Acciones:

- registrar/desregistrar handlers por thread/turn de forma determinista;
- resolver requests pendientes en timeout, cancelación, interrupt y close;
- enviar snapshots explícitos en create/resume y rechazar bindings ausentes;
- demostrar que native authority permanece denegada.

Evidencia: `b4f0c14`, `f747468` (create/resume, cancelación, cleanup y autoridad native denegada).

### P5-TASK-0007 — Completar pruebas unitarias y contractuales

Estado: `done`

Requisitos: `P5-REQ-001`–`P5-REQ-022`

Criterios: `AC-P5-001`–`AC-P5-026`

Acciones:

- crear matrices de schemas, permisos, HITL, retries, dedupe y fallos;
- simular el protocolo Codex sin proceso, red o credenciales;
- reforzar public API, import boundaries, quota safety y cobertura ≥90 %;
- probar LangSmith fake y OpenTelemetry in-memory.

Evidencia: `f747468`: `138 passed, 8 skipped`, cobertura branch-aware `90.11%`, además de
contract tests, quota safety y pruebas de protocolo simuladas.

### P5-TASK-0008 — Documentar, empaquetar y preparar release

Estado: `done`

Requisitos: `P5-REQ-023`, `P5-REQ-024`

Criterios: `AC-P5-026`, `AC-P5-027`, `AC-P5-028`

Acciones:

- crear ADR y ejemplo controlled-agent sin credenciales embebidas;
- actualizar README/API docs, lock y versión `0.6.0`;
- construir e inspeccionar wheel/sdist e instalaciones aisladas;
- preparar smoke opt-in Luna/low y matriz CI.

Evidencia: `9737373`, `b2379f9`, build/artefactos `0.6.0`, instalaciones aisladas, ADR, README,
ejemplo y workflow CI actualizado.

### P5-TASK-0009 — Validar, entregar y cerrar el SDD

Estado: `in_progress — owner review pending`

Requisitos: `P5-REQ-022`, `P5-REQ-023`, `P5-REQ-024`

Criterios: `AC-P5-026`, `AC-P5-027`, `AC-P5-028`

Acciones:

- ejecutar gates locales, artefactos e instalaciones aisladas;
- ejecutar smoke externo sólo con opt-in autorizado;
- publicar commits en inglés y esperar CI Linux/Windows 3.11–3.14;
- registrar evidencia, auditar IDs y solicitar revisión del propietario;
- mover este mismo paquete a `complete/` sólo después de aprobación y cierre total.

Evidencia: gates locales y CI remoto verde registrados en `05_validation_plan.md`; smoke real
Luna/low pasado. Falta únicamente la revisión explícita del propietario para marcar este task
`done` y mover el paquete a `complete/`.
