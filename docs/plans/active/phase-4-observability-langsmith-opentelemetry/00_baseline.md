# Baseline — Phase 4

## Estado auditado

- Commit: `2471858`.
- Versión: `0.4.0`.
- Worktree antes de crear este SDD: limpio.
- Suite: `96 passed, 7 skipped`.
- Ruff: sin hallazgos.
- mypy strict: sin hallazgos en 57 archivos.
- import-linter: 66 archivos, 237 dependencias; contrato core/framework conservado.

Esta evidencia fija el punto de partida y no constituye evidencia de implementación de Phase 4.

## Estado actual confirmado

- `RuntimeEvent` ya es un envelope inmutable con kind, event ID, secuencia, timestamp UTC,
  identidad neutral, invocation/session/turn IDs, metadata y resultado terminal opcional.
- `RuntimeEventKind` cubre lifecycle, invocation, session, turn, token usage, tools, retries,
  validación, capability rejection, interrupción, cancelación y fallos.
- El runner Codex emite eventos ordenados por turno y adjunta `RuntimeResult` al único
  `INVOCATION_COMPLETED`; los retries structured ya emiten `VALIDATION_FAILED` y
  `RETRY_SCHEDULED`.
- `RuntimeUsage` ya contiene tokens, cache tokens, reasoning tokens, duración, turns, tools y
  retries; no toda esa información se proyecta hoy en cada evento terminal.
- `RuntimeDiagnostic` y `ObservabilityError` existen, pero no hay estado de observabilidad,
  dispatcher ni integración entre fallos de exporter y resultados.
- `CodexRuntime.events` es sólo una lista local de lifecycle; no es un bus, no acepta observers y
  sus eventos no se envían a `ainvoke()`/`astream()`.
- `RuntimeNode` propaga metadata LangGraph allowlisted a `InvocationConfig` y publica un envelope
  JSON seguro en `stream_mode="custom"`; ese mecanismo no es un observer/exporter.
- El descriptor persistente `prt1.*` aparece internamente como `session_id`; Phase 3 ya demuestra
  que debe proyectarse como correlación SHA-256 y nunca exportarse directamente.
- `pyproject.toml` sólo declara el extra `langgraph`; no existen extras `langsmith`, `otel` o
  dependencias de observabilidad.
- No existe `proteo_runtime.observability`, observer protocol, redactor, LangSmith observer,
  OpenTelemetry observer ni configuración Codex-native OTel.
- La instalación base y la suite default no requieren red, credenciales ni cuota.

## Decisiones cerradas

- El target de release es `0.5.0` y el paquete SDD se mantiene en `docs/plans/active/`.
- Los contratos neutrales vivirán en `proteo_runtime.observability`; los módulos de exporters
  opcionales importarán sus SDKs de forma aislada y perezosa.
- El bus será async, awaitará cada dispatch y serializará eventos por invocación. No creará tasks
  fire-and-forget ni buffers persistentes propios.
- Los observers se ejecutarán en orden de registro. Un fallo de uno no impedirá que los restantes
  reciban el evento en modo no estricto.
- `metadata_only` será el modo por defecto. Metadata operativa y payload sensible se modelarán por
  separado antes de entregar eventos a exporters oficiales.
- Los descriptors reanudables nunca saldrán del límite runtime; se usará un hash estable,
  namespaced y no reversible como `proteo.session_id` de correlación.
- LangSmith y Proteo OpenTelemetry consumirán el mismo evento neutral, pero serán implementaciones
  independientes. LangSmith no será transporte de OpenTelemetry.
- Proteo OpenTelemetry utilizará tracer/meter providers del host o inyectados; no reemplazará los
  providers globales.
- Codex-native OTel permanecerá deshabilitado por defecto, impondrá `log_user_prompt=false` salvo
  doble opt-in futuro fuera de esta fase, y sólo propagará correlación cuando upstream lo permita.
- El core seguirá sin importar LangSmith, OpenTelemetry, LangGraph, providers u `openai_codex`.
- Toda inferencia real de validación usará `gpt-5.6-luna` con esfuerzo `low`.

## Gaps que implementa la fase

- contratos de observer, configuración, payload mode, status y event bus;
- instrumentación uniforme de lifecycle, modelos, structured output y sesiones;
- metadata terminal completa y segura;
- redacción obligatoria, diagnóstico de degradación y strict mode;
- exporters LangSmith y OpenTelemetry opcionales;
- opt-in Codex-native OTel y capability gating;
- contract tests, ejemplos, smokes, extras, artefactos y documentación pública.

## Riesgos

- Awaitar exporters puede añadir latencia; los adapters deben delegar batching/backgrounding al
  SDK correspondiente y nunca realizar I/O síncrono bloqueante en el event loop.
- Un exporter puede fallar mientras se construye el evento terminal. El resultado entregado al
  host debe reflejar el diagnóstico sin duplicar el terminal ni perder cleanup.
- Eventos de lifecycle no siempre tienen invocation ID; su orden será por runtime y no se
  mezclarán artificialmente con una traza de invocación.
- `OUTPUT_TEXT_DELTA` y `RuntimeResult` contienen contenido potencialmente sensible; ninguna ruta
  default puede exportarlos como payload.
- Parent IDs LangGraph pueden ser inválidos o pertenecer a otro contexto; se validan y, si no son
  utilizables, se crea una raíz Proteo sin fallar inferencia.
- Las APIs de SDKs opcionales y la configuración OTel nativa de Codex evolucionan; los imports y
  capability checks deben fallar con mensajes accionables, nunca degradar silenciosamente.
- Flush/close defectuosos pueden perder telemetría o retrasar shutdown; su semántica y timeout
  deben probarse.

## Gaps no bloqueantes de validación

- LangSmith, un collector OTLP y Codex real requieren opt-in y credenciales/servicios externos.
- Ausencia de soporte upstream para propagar correlation IDs a Codex-native OTel no bloquea los
  exporters neutrales; debe quedar visible como capability no disponible.
- Un `trace_id` compartido con Codex-native OTel no es criterio de Phase 4.
