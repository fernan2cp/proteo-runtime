# Phase 2.1 — Cross-Phase Conformance Hardening

Estado: `active`

Este SDD corrige divergencias de contrato descubiertas después de los cierres históricos de
Phase 0, Phase 1 y Phase 2. Es el tracker autoritativo de la implementación correctiva; los
paquetes históricos permanecen en `docs/plans/complete/`.

## Fuentes y alcance

- Fuente normativa: `docs/design/project-guide.md`.
- Baseline: commit `8dfd4ff`, versión `0.3.0`.
- Alcance: contratos core, lifecycle Codex, configuración/bindings, resume/migration, fakes,
  pruebas semánticas, integración opt-in, packaging y documentación de errata.
- Fuera de alcance: LangGraph, tools, native execution, aislamiento fuerte, retries generales,
  sesiones structured persistentes y cualquier eliminación de historia de usuario.

## Mapa documental

| Documento | Propósito |
|---|---|
| `00_baseline.md` | Estado confirmado y riesgos |
| `01_requirements.md` | Requisitos verificables `C21-REQ-*` |
| `02_technical_design.md` | Diseño de contratos y flujos |
| `03_task_plan.md` | Workstreams `C21-TASK-*` y evidencia |
| `04_acceptance_criteria.md` | Criterios binarios `AC-C21-*` |
| `05_validation_plan.md` | Comandos, pruebas y evidencia requerida |
| `06_rollout_and_rollback.md` | Entrega `0.3.1` y reversión segura |
| `07_traceability.md` | Matrices guía→requisito→tarea→criterio→validación |

## Trazabilidad

Cada tarea referencia al menos un requisito y un criterio; cada requisito aparece en una tarea
y un criterio; cada criterio tiene una validación concreta. La evidencia sólo se marca después
de ejecutar y registrar la validación correspondiente.

