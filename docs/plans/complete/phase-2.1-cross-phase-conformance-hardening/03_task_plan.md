# Task plan

All tasks begin as `pending` and become `in_progress` only while actively implemented.

### C21-TASK-0001 — Register baseline and errata scaffold

Estado: `done`

Requisitos: `C21-REQ-017`

Criterios: `AC-C21-001`, `AC-C21-025`

Acciones: create this package, record baseline, add append-only historical errata references.

Evidencia: paquete registrado en `0fa94aa`; baseline `8dfd4ff` y erratas append-only verificadas.

### C21-TASK-0002 — Correct core contracts

Estado: `done`

Requisitos: `C21-REQ-001`, `C21-REQ-002`, `C21-REQ-003`

Criterios: `AC-C21-002`, `AC-C21-003`, `AC-C21-004`

Acciones: fix native matrix, validate roles, normalize security policy, add focused tests.

Evidencia: `ef1a224`; pruebas unitarias de roles, native y `SecurityPolicy` incluidas en la suite.

### C21-TASK-0003 — Harden Codex terminal and shutdown lifecycle

Estado: `done`

Requisitos: `C21-REQ-004`, `C21-REQ-005`, `C21-REQ-006`

Criterios: `AC-C21-005`–`AC-C21-009`

Acciones: implement exclusive terminal state, missing-terminal failure, stream finalizer and
awaited runtime cleanup in provider code and fakes.

Evidencia: `92d89ef` y `26b94c2`; suite semántica cubre terminales fallidos/interrumpidos, EOF,
los eventos `TURN_INTERRUPTED`/`INTERRUPTED` y cleanup.

### C21-TASK-0004 — Validate configuration and freeze bindings

Estado: `done`

Requisitos: `C21-REQ-007`–`C21-REQ-010`

Criterios: `AC-C21-010`–`AC-C21-015`

Acciones: validate catalog mappings, remove default gate, freeze bindings, enforce factory/schema
rules, cross-validate profiles and preserve JSON paths.

Evidencia: `90ff2bd`; startup, catálogo completo, bindings congelados y perfiles custom validados.

### C21-TASK-0005 — Harden resume and migration

Estado: `done`

Requisitos: `C21-REQ-011`–`C21-REQ-013`

Criterios: `AC-C21-016`–`AC-C21-021`

Acciones: strict descriptors, trusted current policy, busy-safe resume, descriptor-driven
migration, generation invalidation and exact workspace cleanup.

Evidencia: `a5d46a6` y `dbbf714`; resume estricto, migración por descriptor y nonce verificadas.

### C21-TASK-0006 — Align fakes and semantic contract tests

Estado: `done`

Requisitos: `C21-REQ-014`, `C21-REQ-015`

Criterios: `AC-C21-022`, `AC-C21-023`

Acciones: update fake parity and add named tests for every security/lifecycle invariant.

Evidencia: `682a1b3`; fakes y pruebas nominativas cubren invariantes de confianza, lifecycle y structured.

### C21-TASK-0007 — Add opt-in integration and packaging evidence

Estado: `done`

Requisitos: `C21-REQ-016`, `C21-REQ-017`

Criterios: `AC-C21-024`–`AC-C21-027`

Acciones: validate twelve mappings via catalog, run representative smokes, bump version,
update lock/artifact checks, push and verify CI.

Evidencia: suite local `73 passed, 4 skipped`, cobertura branch-aware `90.06%`, build/artefactos e
instalaciones aisladas `0.3.1` validados; integración Codex `5 passed`; CI remoto
`34971422372` (commit `df3f0bc`) verde en Linux/Windows Python 3.11–3.14.

### C21-TASK-0008 — Update guide, docs and close SDD

Estado: `done`

Requisitos: `C21-REQ-017`

Criterios: `AC-C21-001`, `AC-C21-025`–`AC-C21-029`

Acciones: update guide/README/errata, record all evidence, mark done, move package to complete,
commit closure and verify final CI.

Evidencia: guía, README, erratas históricas y workflow actualizados; cierre registrado en el
commit posterior al traslado del paquete a `docs/plans/complete/`.
