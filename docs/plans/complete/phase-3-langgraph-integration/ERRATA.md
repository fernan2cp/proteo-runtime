# ERRATA — Phase 3 LangGraph Integration

Fecha: `2026-09-15`

## Origen

Esta errata registra la auditoría posterior al cierre del SDD y corrige evidencia que era válida
en comportamiento, pero estaba incompleta o descrita con demasiada amplitud. El paquete permanece
en `docs/plans/complete/` y conserva `Estado: complete`.

## Correcciones aplicadas

- Se añadió un contract test de `StateGraph` con structured output JSON Schema.
- Se añadió cobertura de cierre único de `astream()` (`aclose()`) en éxito y cancelación.
- Se añadió un wrapper de prueba que verifica cierre único de sesiones en éxito, error del runtime,
  error de mapper y cancelación.
- Se verificó que el adaptador no llama `session.interrupt()`, `archive()`, `delete()` ni deja
  sesiones fake activas después de cada escenario.
- Las instalaciones base de wheel y sdist ahora comprueban en CI el error accionable al importar
  la integración sin `proteo-runtime[langgraph]`.
- Se añadió `.gitattributes` para fijar Markdown en LF y hacer reproducible `ruff format --check`
  en Windows.
- Se corrigieron las referencias de CI: `34982580419` es la validación previa al cierre y
  `34982994292` valida el commit de cierre `5f89f74`.
- Se aclaró que el ejemplo público usa el runtime del host; los contract tests usan `FakeRuntime`.

## Criterios afectados

Las correcciones aportan evidencia adicional para `AC-P3-008`, `AC-P3-017`, `AC-P3-018`,
`AC-P3-020` y `AC-P3-025`. No cambian requisitos, diseño técnico, API pública, envelope JSON,
ownership de sesiones ni alcance de Phase 3.

## Evidencia de implementación

- Tests focalizados actualizados en `tests/unit/test_langgraph_node.py` y
  `tests/contract/test_langgraph_adapter.py`.
- Guard de instalación base actualizado en `.github/workflows/ci.yml`.
- Política EOL añadida en `.gitattributes`.
- Matrices y validación corregidas en `README.md`, `01_requirements.md`, `03_task_plan.md`,
  `04_acceptance_criteria.md`, `05_validation_plan.md` y `07_traceability.md`.

La validación local posterior quedó en `96 passed, 7 skipped`, cobertura branch-aware `90.41 %`,
Ruff format/check, mypy, import-linter, pre-commit, checker de artefactos, lock e instalaciones
base aisladas verdes. Los smokes Codex no se repitieron porque estas correcciones no cambian
runtime ni proveedor; permanece válida la evidencia opt-in previa de Luna/low.
