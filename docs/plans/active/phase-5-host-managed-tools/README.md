# Phase 5 — Host-Managed Tools

Estado: `active`

Este SDD es el tracker autoritativo para implementar herramientas administradas por el host en
Proteo Runtime. La fase permite que Codex seleccione y encadene capacidades de negocio declaradas
por la aplicación, mientras el host conserva el registro, los permisos, la aprobación, la
ejecución, los efectos laterales y la auditoría.

## Fuentes

- Fuente normativa: `docs/design/project-guide.md`, especialmente §2.1, R-014–R-017, R-022,
  R-023, R-027, R-029, §9, §12–§15, §19, §21–§25 y roadmap Phase 5.
- Protocolo upstream: documentación oficial de Codex App Server para `dynamicTools` y
  `item/tool/call`, marcada experimental.
- Baseline de código: commit `5b9d0be`, versión `0.5.0`.
- Baseline de SDK: `openai-codex==0.147.0` y su runtime fijado.
- Contratos existentes: `Runtime`, `RuntimeModel`, `RuntimeSession`, `RuntimeCapabilities`,
  perfiles, errores, `RuntimeEvent`, `RuntimeResult`, event bus y observers oficiales.

## Alcance

- namespace neutral `proteo_runtime.tools`;
- definición, registro y snapshot inmutable de tools;
- generación y validación host-side de schemas de entrada y salida;
- permisos exactos, clasificación de efectos laterales y aprobación humana async;
- executor async con timeout, deduplicación, retries idempotentes y políticas de fallo;
- binding inmutable en modelos y binding explícito en sesiones tool-enabled;
- eventos, redacción, LangSmith y OpenTelemetry para el ciclo completo de una tool;
- adapter Codex experimental con feature flag, capability check y shim JSON-RPC privado;
- fakes, contract tests, ejemplo, ADR, packaging y release `0.6.0`;
- CI Linux/Windows para Python 3.11–3.14.

## Fuera de alcance

- aislamiento fuerte de proceso, filesystem y red de Phase 6;
- habilitación de shell, escritura, browser, MCP arbitrario o native tools de Codex;
- retry/backoff/jitter general de transportes y recuperación de sesión de Phase 7;
- fallback automático, routing, account rotation o providers adicionales;
- persistencia de callables, permisos, aprobaciones, resultados o caches de idempotencia;
- ejecución de funciones sync mediante threads o procesos;
- parsing de llamadas a tools desde texto o prompts como fallback del protocolo;
- cambios al schema JSON de resolución de modelos.

## Mapa documental

| Documento | Propósito |
|---|---|
| `00_baseline.md` | Estado confirmado, decisiones cerradas, gaps y riesgos |
| `01_requirements.md` | Requisitos verificables `P5-REQ-*` |
| `02_technical_design.md` | Contratos, flujo, seguridad, observabilidad y adapter Codex |
| `03_task_plan.md` | Tareas `P5-TASK-*`, estado y evidencia futura |
| `04_acceptance_criteria.md` | Criterios binarios `AC-P5-*` |
| `05_validation_plan.md` | Suites, comandos, smokes y evidencia requerida |
| `06_rollout_and_rollback.md` | Entrega `0.6.0`, gates, compatibilidad y reversión |
| `07_traceability.md` | Matrices guía→requisito→tarea→criterio→validación |

## Regla de trazabilidad y cierre

Cada tarea referencia al menos un requisito y un criterio; cada requisito aparece en al menos una
tarea y un criterio; cada criterio identifica evidencia automatizada, inspección o integración.
Todos los IDs comienzan `pending`. Ningún ID pasa a `done` sin evidencia concreta y reproducible.

El paquete se moverá, sin renombrarlo, a `docs/plans/complete/` sólo cuando la implementación,
todos los criterios, gates locales, smoke Codex, CI final y revisión explícita del propietario
estén completos. Si el cierre descubre trabajo faltante, se reabre o amplía este mismo SDD; no se
crea un plan paralelo de cierre.
