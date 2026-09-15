# Baseline — Phase 3

## Estado auditado

- Commit: `4c05919`.
- Rama: `integ/phase-3-langgraph-integration`.
- Versión: `0.3.1`.
- Worktree antes de crear este SDD: limpio.
- Suite: `73 passed, 5 skipped`.
- Ruff: sin hallazgos.
- mypy strict: sin hallazgos en 52 archivos.
- import-linter: contrato core/framework conservado, 61 archivos y 219 dependencias analizadas.

La evidencia anterior se obtuvo con los ejecutables del entorno virtual local. No constituye
evidencia de Phase 3; sólo fija el punto de partida.

## Estado actual confirmado

- `src/proteo_runtime/integrations/__init__.py` sólo reserva el límite de integraciones.
- `pyproject.toml` no define extras `langgraph` ni `all` y el lock no incluye LangGraph.
- `proteo_runtime.core` expone protocolos async neutrales y tiene prohibido importar LangGraph,
  LangSmith, OpenTelemetry, providers u `openai_codex`.
- `RuntimeModel` y `RuntimeSession` exponen `ainvoke()` y `astream()`; el stream termina con un
  `RuntimeEvent` que contiene el `RuntimeResult` lógico.
- `RuntimeInput` acepta texto o mensajes neutrales; no acepta estados de frameworks.
- `RuntimeResult.value` contiene la salida de texto, Pydantic o JSON Schema; `raw` es opt-in.
- `RuntimeSession.descriptor` es el identificador opaco y autocontenido persistido por el host.
- `FakeRuntime` cubre modelos, structured output, streaming, sesiones y cancelación sin red,
  credenciales ni cuota.
- La suite contractual comprueba que core y testing no cargan frameworks ni providers.
- No existe todavía un ejemplo LangGraph ni un test StateGraph.

## Decisiones cerradas

- La única superficie pública de esta fase será
  `proteo_runtime.integrations.langgraph.RuntimeNode`.
- El nodo recibe un `RuntimeModel` para ejecución efímera/structured o un `Runtime` para reanudar
  una sesión; nunca recibe objetos Codex.
- El estado usa por defecto claves `input` y `output`; mappers opcionales permiten otras formas.
- Un nodo persistente requiere `configurable.proteo_session_id`; no crea sesiones.
- El descriptor no se copia al estado ni al stream automáticamente.
- Los eventos se proyectan como JSON versionado en el stream `custom` de LangGraph.
- La salida normal del nodo contiene sólo el mapping producido desde `RuntimeResult.value`.
- La metadata se propaga de forma allowlisted y validada, nunca copiando todo `RunnableConfig`.
- El target de release es `0.4.0`.
- El envelope nunca expone `session_id` reanudable; usa `session_correlation_id` como SHA-256
  estable del descriptor para correlación no reanudable.
- La cancelación usa `astream().aclose()` como única señal neutral de interrupción. Si un runtime
  la normaliza como `CancellationError` mientras el task LangGraph sigue cancelándose, el adapter
  restaura `asyncio.CancelledError` sin invocar `session.interrupt()` por segunda vez.
- Toda inferencia Codex real de esta fase usará `gpt-5.6-luna` con reasoning `low`.

## Gaps que implementa la fase

- dependencia opcional e import error accionable;
- API tipada y callable compatible con StateGraph;
- conversión de estado y resultados;
- proyección JSON de eventos y captura del resultado terminal;
- propagación de cancelación y cleanup;
- sesión reanudada mediante configuración del checkpointer/host;
- pruebas, ejemplos, documentación, packaging y matriz CI.

## Riesgos

- LangGraph puede agregar metadata interna no JSON; sólo se copiará un conjunto permitido.
- Un stream abandonado podría dejar trabajo activo si no se cierra explícitamente.
- Reanudar un descriptor por nodo puede crear handles transitorios; cada handle debe cerrarse en
  `finally` sin archivar ni borrar la historia.
- El output del modelo es contenido de aplicación y puede ser sensible; no se duplicará en el
  stream de eventos. La política semántica sobre `result.value` sigue siendo responsabilidad del
  host.
- El extra debe funcionar en Python 3.11–3.14 aunque los metadatos upstream puedan no anunciar
  todavía todos esos intérpretes; la matriz CI es el criterio real de compatibilidad.

## Gaps no bloqueantes de validación

- La integración real con Codex consume cuota y requiere opt-in explícito.
- La ejecución CI remota sólo puede registrarse después de publicar la rama de implementación.
- LangSmith/OpenTelemetry no deben usarse para demostrar streaming en esta fase.
