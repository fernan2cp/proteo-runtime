# Phase 3 — LangGraph Integration

Estado: `complete`

Este SDD es el tracker autoritativo para implementar la integración inicial de Proteo Runtime
con LangGraph. La fase introduce un único adaptador público y provider-neutral, conserva el
estado global y la persistencia bajo control del host, y no adelanta observabilidad ni tools.

## Fuentes

- Fuente normativa: `docs/design/project-guide.md`, especialmente R-002, R-009, R-019,
  R-020, R-022, R-028, secciones 21–25 y roadmap Phase 3.
- Baseline de código: commit `4c05919`, versión `0.3.1`.
- Contratos existentes: `Runtime`, `RuntimeModel`, `RuntimeSession`, `RuntimeInput`,
  `RuntimeResult`, `InvocationConfig` y `RuntimeEvent`.
- Decisiones de alcance confirmadas por el usuario: mapeo por claves con mappers opcionales,
  sesión preexistente obligatoria y streaming custom mediante eventos neutrales JSON.

## Alcance

- extra opcional `langgraph>=1.2,<2` y actualización del lock;
- `proteo_runtime.integrations.langgraph.RuntimeNode` como única superficie pública nueva;
- nodos async efímeros, structured y de sesión reanudada;
- mapeo configurable entre estado y contratos neutrales;
- propagación segura de `RunnableConfig`;
- streaming custom JSON y cancelación;
- pruebas sin cuota, ejemplo StateGraph y smoke Codex opt-in;
- documentación, artefactos, release `0.4.0` y CI Linux/Windows.

## Fuera de alcance

- `BaseChatModel`, `CodexNode`, `ChatRuntime` y adaptadores LangChain;
- creación automática de sesiones o mutación automática del estado con un descriptor;
- LangSmith, OpenTelemetry y cualquier observer de Phase 4;
- host-managed tools, native tools, nuevos perfiles de seguridad o aislamiento fuerte;
- adaptadores para otros frameworks y cambios en objetos del SDK Codex.

## Mapa documental

| Documento | Propósito |
|---|---|
| `00_baseline.md` | Estado confirmado, decisiones, gaps y riesgos |
| `01_requirements.md` | Requisitos verificables `P3-REQ-*` |
| `02_technical_design.md` | API, flujos, streaming, sesiones y fallos |
| `03_task_plan.md` | Tareas `P3-TASK-*`, estado y evidencia futura |
| `04_acceptance_criteria.md` | Criterios binarios `AC-P3-*` |
| `05_validation_plan.md` | Pruebas, comandos y evidencia requerida |
| `06_rollout_and_rollback.md` | Entrega `0.4.0`, compatibilidad y reversión |
| `07_traceability.md` | Matrices guía→requisito→tarea→criterio→validación |

## Regla de trazabilidad y cierre

Cada tarea referencia al menos un requisito y un criterio; cada requisito aparece en una tarea y
un criterio; cada criterio tiene validación concreta. Ninguna tarea pasa a `done` sin evidencia
registrada. El paquete se moverá, sin renombrarlo, a `docs/plans/complete/` sólo cuando la
implementación, todos los criterios, la validación local y el CI final estén completos. Evidencia
CI final: https://github.com/fernan2cp/proteo-runtime/actions/runs/34982580419.
