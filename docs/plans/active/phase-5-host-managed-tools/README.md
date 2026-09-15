# Phase 5 — Host-Managed Tools

Estado: `in_progress — owner review pending`

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

## Evidencia de implementación

- Commits funcionales: `900bdd5`, `b4f0c14`, `5300776`, `b99131c`, `f747468`, `9737373`,
  `b2379f9` y la corrección del bridge `08445fc`; el commit inicial del SDD `ba78016` se
  conserva.
- Gates locales: `uv lock --check`, Ruff format/check, mypy strict (69 archivos), import-linter
  (79 archivos/325 dependencias), pre-commit, pytest branch-aware (`138 passed, 8 skipped`,
  cobertura `90.11%`), quota safety, build, inspección de artefactos e instalaciones aisladas.
- Artefactos: wheel SHA-256
  `BEABD6DBF4BA225B8C9CFF6ED4DE4C2D750B22E0B78945E8A8CD397A64C594A6`; sdist SHA-256
  `4B56C551BEF28E4F7BA1CD051035125E1D6A7384CB0DF234D117F59C54EF5B72`.
- Smoke Codex opt-in: `tests/integration/codex/test_dynamic_tools_smoke.py` pasó con
  `PROTEO_CODEX_DYNAMIC_TOOLS_INTEGRATION=1`, `gpt-5.6-luna`/`low` y dos ejecuciones host-side
  reales, verificadas por eventos `tool_completed`.
- CI remoto verde: [run 35027524386](https://github.com/fernan2cp/proteo-runtime/actions/runs/35027524386)
  sobre el bridge corregido y [run 35027764791](https://github.com/fernan2cp/proteo-runtime/actions/runs/35027764791)
  sobre el commit de evidencia; ambos cubren Ubuntu/Windows y Python 3.11–3.14, incluyendo
  packaging.

El estado global y `P5-TASK-0009` permanecen `in_progress — owner review pending` por decisión
del propietario. Esta carpeta no se mueve hasta recibir confirmación explícita.
