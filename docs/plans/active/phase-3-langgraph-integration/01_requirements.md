# Requirements — Phase 3

Todos los requisitos comienzan con estado `pending`.

## Dependencia y API pública

- `P3-REQ-001`: LangGraph MUST ser una dependencia opcional `langgraph>=1.2,<2`; instalar o
  importar el paquete base MUST NOT cargar LangGraph.
- `P3-REQ-002`: La única superficie pública inicial MUST ser
  `proteo_runtime.integrations.langgraph.RuntimeNode`; no se añadirán exports en el paquete raíz
  ni compatibilidad `BaseChatModel`, `CodexNode`, `ChatRuntime` o LangChain.
- `P3-REQ-003`: `RuntimeNode` MUST aceptar exactamente un ejecutor neutral: `RuntimeModel` para
  invocaciones efímeras/structured o `Runtime` para reanudar sesiones persistentes.

## Estado, entrada y salida

- `P3-REQ-004`: Sin mappers, el nodo MUST leer `state[input_key]`, con `input_key="input"` por
  defecto, normalizarlo como `str | RuntimeInput` y devolver `{output_key: result.value}`, con
  `output_key="output"` por defecto.
- `P3-REQ-005`: `input_mapper` MAY aceptar cualquier estado y MUST devolver `str | RuntimeInput`;
  `output_mapper` MUST recibir `RuntimeResult` y devolver un `Mapping[str, Any]` que el nodo copie
  antes de entregarlo a LangGraph.
- `P3-REQ-006`: Structured output MUST reutilizar un `RuntimeModel` ya enlazado mediante
  `with_structured_output()`; el adaptador no reinterpretará schemas ni validará de nuevo valores.
- `P3-REQ-007`: El estado devuelto por defecto MUST NOT contener `RuntimeResult`, `RuntimeEvent`,
  descriptors, handles de sesión ni objetos específicos de provider.

## RunnableConfig y metadata

- `P3-REQ-008`: El nodo MUST aceptar `RunnableConfig | None` como segundo argumento async sin
  modificar el objeto recibido.
- `P3-REQ-009`: Sólo `metadata["proteo"]`, `tags`, `run_id` y los campos framework
  `langgraph_node`, `langgraph_step` y `langgraph_triggers` MAY convertirse a
  `InvocationConfig.metadata`.
- `P3-REQ-010`: Metadata con claves secret-shaped, valores no JSON o formas inválidas MUST fallar
  antes del runtime; otros campos de `RunnableConfig` MUST ignorarse y el descriptor MUST NOT
  aparecer en metadata o eventos.

## Streaming y cancelación

- `P3-REQ-011`: El nodo MUST consumir `executor.astream()` para conservar streaming y MUST
  publicar cada `RuntimeEvent` como un envelope JSON v1 en el writer `custom` de LangGraph.
- `P3-REQ-012`: El envelope MUST contener tipo, versión, kind, sequence, timestamp, identidad
  neutral mínima, invocation/turn IDs y `session_correlation_id` derivado por SHA-256; MUST omitir
  el descriptor reanudable, `RuntimeResult.value`, `raw`, SDK objects y metadata insegura.
- `P3-REQ-013`: Un único evento `INVOCATION_COMPLETED` MUST proporcionar internamente el
  `RuntimeResult` usado para construir el update final; EOF sin resultado o terminales exitosos
  múltiples MUST fallar explícitamente.
- `P3-REQ-014`: Cancelar o abandonar la llamada MUST cerrar el iterador para activar la
  interrupción del runtime, limpiar handles transitorios y volver a lanzar `CancelledError` si la
  cancelación pertenece al task LangGraph; no debe llamar `session.interrupt()` duplicadamente.

## Sesiones y errores

- `P3-REQ-015`: El modo `Runtime` MUST exigir un `str` no vacío en
  `configurable.proteo_session_id` y fallar antes de provider access si está ausente o mal tipado.
- `P3-REQ-016`: El nodo MUST llamar `resume_session()`, ejecutar exactamente un turno y cerrar el
  handle en `finally`; nunca creará, archivará, borrará o migrará una sesión.
- `P3-REQ-017`: Un descriptor entregado a un nodo `RuntimeModel` MUST rechazarse para evitar
  mezcla accidental de contexto; errores `AgentRuntimeError` y errores de mappers del host se
  preservarán sin convertirlos en excepciones de LangGraph.

## Calidad, ejemplo y entrega

- `P3-REQ-018`: Pruebas unitarias y contractuales MUST usar `FakeRuntime`; `pytest` por defecto
  MUST seguir sin credenciales, red o cuota.
- `P3-REQ-019`: Debe existir un ejemplo StateGraph que demuestre brain, structured y sesión
  precreada sin almacenar objetos Codex en el estado; el smoke Codex será opt-in.
- `P3-REQ-020`: La release `0.4.0` MUST incluir documentación pública, lock, extras y artefactos
  consistentes, y pasar validación local más CI Linux/Windows Python 3.11–3.14.
- `P3-REQ-021`: Toda inferencia Codex real de Phase 3 MUST usar `gpt-5.6-luna` con esfuerzo
  `low`; los tests de catálogo que no invocan inferencia MAY inspeccionar otros mappings.

## Estado de implementación

`P3-REQ-001`–`P3-REQ-019` y `P3-REQ-021`: `done`, con evidencia en los tests unitarios y
contractuales, el ejemplo, los smokes opt-in y los gates locales indicados en `05_validation_plan.md`.
`P3-REQ-020`: `in_progress`; la validación local de release está completa y queda pendiente el
CI remoto Linux/Windows para cerrar el requisito.
