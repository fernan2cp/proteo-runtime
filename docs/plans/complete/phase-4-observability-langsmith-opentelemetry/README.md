# Phase 4 — Observability, LangSmith and OpenTelemetry

Estado: `active`

Este SDD es el tracker autoritativo para implementar la observabilidad oficial de Proteo Runtime
desde Phase 4. La fase completa el bus de eventos neutral, incorpora observers LangSmith y
OpenTelemetry independientes, y permite enriquecimiento OpenTelemetry nativo de Codex sólo con
opt-in y capability gating.

## Fuentes

- Fuente normativa: `docs/design/project-guide.md`, especialmente §2.4, R-010, R-011, R-022,
  R-027, secciones 14–16, 21–25 y roadmap Phase 4.
- Baseline de código: commit `2471858`, versión `0.4.0`.
- Contratos existentes: `Runtime`, `RuntimeModel`, `RuntimeSession`, `RuntimeEvent`,
  `RuntimeResult`, `RuntimeUsage`, `RuntimeDiagnostic`, `InvocationConfig`, `ContextPolicy` y
  `RuntimeNode`.
- Decisiones de alcance confirmadas: release `0.5.0`, extras independientes, payload
  `metadata_only` por defecto, exporters neutrales separados y Codex-native OTel opt-in.

## Alcance

- namespace neutral `proteo_runtime.observability` y event bus async;
- observer protocol, configuración, lifecycle y estado de salud;
- metadata canónica, correlación no reanudable y política de payload/redacción;
- degradación aislada por defecto y strict mode explícito;
- `LangSmithObserver` opcional con jerarquía anidada y parent LangGraph cuando exista;
- `OpenTelemetryObserver` opcional con spans y métricas provider-neutral;
- configuración Codex-native OTel explícita, privada y capability-gated;
- fakes, contract tests, ejemplos, smokes opt-in, packaging y release `0.5.0`;
- CI Linux/Windows para Python 3.11–3.14.

## Fuera de alcance

- host-managed tools, ejecución de tools y políticas de Phase 5;
- nuevos backends de observabilidad distintos de LangSmith/OpenTelemetry;
- logs OpenTelemetry propios de Proteo, collector embebido o backend administrado;
- `doctor`, dashboards, alertas remotas o configuración operacional de Phase 7;
- lectura, copia o persistencia de credenciales de LangSmith, OTLP o Codex;
- cambios al schema JSON de resolución de modelos, fallback automático o nuevos providers;
- garantías sobre chain-of-thought, actividad no expuesta o `trace_id` compartido con Codex.

## Mapa documental

| Documento | Propósito |
|---|---|
| `00_baseline.md` | Estado confirmado, decisiones, gaps y riesgos |
| `01_requirements.md` | Requisitos verificables `P4-REQ-*` |
| `02_technical_design.md` | APIs, flujo de eventos, exporters, privacidad y fallos |
| `03_task_plan.md` | Tareas `P4-TASK-*`, estado y evidencia futura |
| `04_acceptance_criteria.md` | Criterios binarios `AC-P4-*` |
| `05_validation_plan.md` | Pruebas, comandos, smokes y evidencia requerida |
| `06_rollout_and_rollback.md` | Entrega `0.5.0`, compatibilidad y reversión |
| `07_traceability.md` | Matrices guía→requisito→tarea→criterio→validación |

## Regla de trazabilidad y cierre

Cada tarea referencia al menos un requisito y un criterio; cada requisito aparece en al menos una
tarea y un criterio; cada criterio nombra evidencia automatizada, inspección o integración. Todos
los IDs nuevos comienzan `pending`. Ningún ID pasa a `done` sin registrar evidencia concreta.

El paquete se moverá, sin renombrarlo, a `docs/plans/complete/` sólo cuando la implementación,
todos los criterios, la validación local, el CI final y la revisión explícita del propietario estén
completos. Este trabajo no lo mueve a `complete/`. Si el cierre descubre trabajo faltante, se
reabre o amplía este mismo SDD; no se crea un plan paralelo de cierre.
