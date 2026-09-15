# Baseline — Phase 5

## Estado auditado

- Commit: `5b9d0be`.
- Versión: `0.5.0`.
- Worktree antes de crear este SDD: limpio.
- Suite: `121 passed, 7 skipped`.
- Ruff: sin hallazgos.
- mypy strict: sin hallazgos en 46 archivos fuente.
- import-linter: 76 archivos, 292 dependencias; contrato core/framework/provider conservado.

Esta evidencia fija el punto de partida y no constituye evidencia de implementación de Phase 5.

## Estado actual confirmado

- `RuntimeCapabilities` ya declara `host_tools` y `native_tools`, ambos falsos en Codex.
- `controlled_agent` ya usa lifecycle efímero, contexto externo, host tools controladas y
  `SecurityPolicy.CONTROLLED_TOOLS`; los demás perfiles built-in mantienen tools deshabilitadas o
  provider-defined.
- `ToolDeniedError`, `ToolExecutionError` y `RetryExhaustedError` ya forman parte del error model.
- `RuntimeEventKind` ya contiene `TOOL_REQUESTED`, `TOOL_STARTED` y `TOOL_COMPLETED`; no existen
  eventos específicos para aprobación, denegación, fallo o retry de tool.
- `RuntimeEvent` ya separa metadata operativa de payload y el bus aplica proyección/redacción.
- LangSmith y OpenTelemetry ya reconocen spans/runs básicos de tools, pero no el ciclo Phase 5.
- `RuntimeModel` no expone `with_tools()`; `Runtime.session()` y `resume_session()` no reciben un
  binding de tools.
- `CodexRuntime` rechaza hoy `controlled_agent` antes de inferencia porque su capability efectiva
  de host tools es falsa.
- Todas las invocaciones Codex actuales fijan `approval_mode=deny_all` y sandbox read-only; no hay
  registro ni executor host-side.
- No existe `proteo_runtime.tools`, decorator, schema generator, registry, executor, permission
  policy, approval handler, tool retry policy ni cache por `call_id`.
- El SDK fijado expone modelos generados `DynamicToolSpec` y `DynamicToolCallThreadItem`, pero su
  superficie estable no ofrece el ciclo completo para responder `item/tool/call`.
- App Server documenta `dynamicTools` en `thread/start` y `item/tool/call` como APIs
  experimentales que requieren `capabilities.experimentalApi`.
- La suite default no usa red, credenciales ni cuota de suscripción.

## Decisiones cerradas

- El target de release es `0.6.0` y el SDD permanece bajo `docs/plans/active/` hasta su cierre.
- Los contratos neutrales vivirán en `proteo_runtime.tools`; el adapter experimental vivirá bajo
  `proteo_runtime.providers.codex.experimental`.
- La API principal será `RuntimeModel.with_tools(registry, executor=...)`, que captura un snapshot
  inmutable sin modificar el modelo de origen.
- Las sesiones tool-enabled reciben registry/executor al crear o reanudar; el host debe volver a
  enlazar implementaciones en cada resume.
- Sólo se aceptan callables `async def` completamente tipados en Phase 5.
- Los permisos usan coincidencia exacta y no admiten wildcards implícitos.
- `SideEffect` usa `none`, `read`, `write` y `destructive`; aprobación usa `never`, `always` y
  `for_side_effects`.
- Timeout de ejecución default: 30 segundos. Timeout de aprobación default: 60 segundos.
- Retry default: un intento total. Sólo tools idempotentes pueden configurar dos o tres intentos.
- La política default devuelve un `ToolResult` sanitizado al modelo; `raise` corta la invocación.
- Cada `call_id` se ejecuta como máximo una vez por invocación; duplicados comparten el mismo
  resultado pending o terminal.
- `controlled_agent` conserva native tools denegadas, `approval_mode=deny_all`, sandbox read-only
  y workspace temporal vacío.
- La integración Codex requiere simultáneamente flag explícito y capability upstream confirmada.
- No habrá fallback por prompt parsing si el protocolo experimental es incompatible.
- Toda inferencia real de validación usa `gpt-5.6-luna` con reasoning `low`.

## Gaps que implementa la fase

- contratos neutrales, schemas, decorator, registry y snapshots;
- permisos, HITL, executor, timeouts, retries, deduplicación y failure policy;
- bindings de modelos/sesiones y cálculo correcto de capabilities efectivas;
- ciclo observable completo y proyección segura de argumentos/resultados;
- shim Codex experimental, server-request handling y compatibility gating;
- fakes, pruebas contractuales, ejemplo, ADR, artefactos y documentación pública.

## Riesgos

- El protocolo experimental puede cambiar dentro del rango SDK; el shim debe validar formas y
  fallar cerrado antes de inferencia.
- Un server request puede llegar mientras el stream se cancela; debe resolverse/denegarse y
  liberar tasks, locks y cache de deduplicación sin dejar el turno colgado.
- Un callable que ignora cancelación puede exceder el timeout; Phase 5 sólo admite async y no
  promete terminar trabajo externo que la propia implementación haya desacoplado.
- Retries de una tool marcada idempotente siguen dependiendo de que esa declaración sea veraz;
  el host conserva esa responsabilidad.
- Argumentos, outputs y mensajes de excepción pueden contener secretos; sólo viajan en payload y
  pasan por la redacción de Phase 4.
- Las dynamic tools pueden persistir como metadata del thread Codex; el runtime debe reemplazar
  explícitamente el listado al reanudar y nunca asumir que implica implementación disponible.
- Incorporar tools a sesiones cambia protocolos públicos pre-1.0; contract tests deben impedir
  que los parámetros opcionales rompan callers existentes.
