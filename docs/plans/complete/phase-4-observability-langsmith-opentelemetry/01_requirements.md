# Requirements — Phase 4

Todos los requisitos comienzan en estado `pending`.

## Packaging y contratos neutrales

- `P4-REQ-001`: La instalación base MUST seguir sin LangSmith/OpenTelemetry; deben existir extras
  `langsmith` con `langsmith>=0.12,<0.13`, `otel` con `opentelemetry-api>=1.44,<2`, y `all` MUST
  incluir `langgraph`, `langsmith` y `otel`. El SDK OTel sólo será dependencia de desarrollo/test.
- `P4-REQ-002`: `proteo_runtime.observability` MUST exponer contratos neutrales tipados para
  observer, event bus, configuración, payload mode y status, sin importar frameworks, providers o
  SDKs de exporters.
- `P4-REQ-003`: `RuntimeObserver` MUST ofrecer lifecycle async `on_event()`, `flush()` y `close()`;
  todos los métodos deben ser idempotentes respecto de recursos ya cerrados y no deben otorgar
  autoridad de ejecución al observer.
- `P4-REQ-004`: El event bus MUST despachar cada evento exactamente una vez por observer, en orden
  causal por invocación y en orden de registro, sin tasks fire-and-forget.
- `P4-REQ-005`: Lifecycle, `ainvoke()`, `astream()`, structured retries y sesiones MUST usar el
  mismo bus; consumir por invoke o stream no puede duplicar eventos ni cambiar el resultado lógico.

## Metadata, correlación y privacidad

- `P4-REQ-006`: Los eventos MUST proporcionar metadata normalizada suficiente para runtime,
  versión, profile, security/context policy, model, reasoning effort, lifecycle, structured flag,
  tokens, latencia, retry/tool counts, errores e invocation/session/turn correlation IDs cuando
  cada dato esté expuesto por Proteo o el provider.
- `P4-REQ-007`: Los exporters MUST usar `proteo.invocation_id`, `proteo.session_id` y
  `proteo.turn_id`; `proteo.session_id` MUST ser una correlación estable no reversible y MUST NOT
  contener el descriptor reanudable.
- `P4-REQ-008`: Los modos MUST ser `metadata_only`, `redacted`, `full` y `disabled`.
  `metadata_only` MUST excluir prompts, respuestas, schemas, tool arguments/results y provider raw;
  `redacted` MUST conservar sólo una representación estructural redactada; `full` MAY conservar
  contenido neutral literal; `disabled` MUST evitar dispatch al observer correspondiente.
- `P4-REQ-009`: La redacción obligatoria de secretos MUST aplicarse también en `full`, recorrer
  mappings/sequences/texto, eliminar exception causes y objetos provider, y no mutar eventos,
  inputs, resultados o metadata originales.
- `P4-REQ-010`: En modo no estricto, un fallo de observer MUST quedar aislado, producir un
  `RuntimeDiagnostic` seguro, marcar status `degraded`, permitir los observers restantes y no
  cambiar success/failure de inferencia.
- `P4-REQ-011`: En strict mode, cualquier fallo de dispatch/flush/close MUST elevar
  `ObservabilityError` sólo después de ejecutar cleanup requerido; la excepción no debe contener
  secretos ni ocultar una cancelación activa.

## LangSmith

- `P4-REQ-012`: `LangSmithObserver` MUST ser opcional, importar LangSmith sólo al configurar el
  observer y emitir una instrucción accionable `proteo-runtime[langsmith]` si falta el extra.
- `P4-REQ-013`: El observer MUST construir runs anidados runtime→turn→retry/validation/tool a
  partir de eventos neutrales y, cuando `langgraph_run_id` sea válido, enlazar la raíz Proteo como
  child del run LangGraph sin importar LangGraph.
- `P4-REQ-014`: LangSmith MUST mapear metadata, status, usage, errores y tags permitidos, respetar
  payload mode, finalizar runs en todos los terminales y soportar flush/close deterministas.

## Proteo OpenTelemetry

- `P4-REQ-015`: `OpenTelemetryObserver` MUST ser opcional, importar sólo OpenTelemetry API al
  configurarse y emitir una instrucción accionable `proteo-runtime[otel]` si falta el extra.
- `P4-REQ-016`: El observer MUST emitir spans neutrales para lifecycle, invocations, turns,
  retries, validation y tools, y métricas para invocaciones, errores, latencia, tokens, cache,
  retries y tool calls sin afirmar datos no expuestos.
- `P4-REQ-017`: El observer MUST aceptar tracer/meter providers o instrumentos inyectados y MAY
  usar los globales del host; MUST NOT instalar, reemplazar ni cerrar providers globales que no
  posee.
- `P4-REQ-018`: LangSmith y OpenTelemetry MUST conservar los mismos tres IDs Proteo y atributos
  semánticos, sin prometer igualdad de `trace_id` entre exporters.

## Codex-native OTel, calidad y entrega

- `P4-REQ-019`: La configuración Codex-native OTel MUST ser provider-specific, tipada, explícita,
  deshabilitada por defecto y capability-gated antes de iniciar el proceso; una configuración no
  aplicable MUST fallar antes de inferencia con error neutral accionable.
- `P4-REQ-020`: Codex-native OTel MUST fijar `log_user_prompt=false` por defecto, no aceptar
  secretos persistidos en config Proteo ni exponer headers/credenciales en argumentos,
  diagnostics o traces; correlación se propagará sólo cuando upstream la soporte.
- `P4-REQ-021`: Ningún exporter MUST afirmar visibilidad de chain-of-thought, hidden reasoning o
  actividad no presente en `RuntimeEvent`, `RuntimeUsage` o telemetría nativa explícitamente
  habilitada.
- `P4-REQ-022`: Tests unitarios/contractuales MUST usar fakes o exporters in-memory; la suite
  default MUST seguir sin credenciales, red, collector externo o cuota.
- `P4-REQ-023`: La release `0.5.0` MUST incluir documentación, ejemplo LangGraph metadata-only,
  lock, extras y artefactos consistentes, y pasar gates locales más CI Linux/Windows 3.11–3.14.
- `P4-REQ-024`: Smokes LangSmith/OTLP/Codex-native MUST ser separados y opt-in; toda inferencia
  Codex real MUST usar `gpt-5.6-luna` con reasoning `low` y registrar evidencia sanitizada.

## Estado de implementación

- `P4-REQ-001`–`P4-REQ-022`: `implemented-local` (código y pruebas locales presentes).
- `P4-REQ-023`: `in_progress` (artefactos y gates locales presentes; CI multi-OS pendiente).
- `P4-REQ-024`: `pending` (smokes externos opt-in no ejecutados sin credenciales/autorización).

Estos estados no autorizan el cierre: el paquete permanece en `active/` hasta completar la
evidencia externa y la revisión del propietario del SDD.
