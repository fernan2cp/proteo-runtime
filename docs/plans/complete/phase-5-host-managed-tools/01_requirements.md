# Requirements — Phase 5

Todos los requisitos comienzan en estado `pending`.

## Contratos, schemas y registro

- `P5-REQ-001`: `proteo_runtime.tools` MUST exponer contratos provider-neutral y MUST NOT importar
  Codex, frameworks, observers ni SDKs externos; Phase 5 MUST agregar cero dependencias runtime.
- `P5-REQ-002`: `runtime_tool` MUST aceptar sólo callables async completamente tipados, generar
  schemas Draft 2020-12 de entrada/salida y rechazar al registrar firmas ambiguas, variádicos,
  anotaciones ausentes, nombres inválidos o schemas no válidos.
- `P5-REQ-003`: `ToolRegistry` MUST rechazar nombres duplicados, conservar orden determinista y
  producir snapshots inmutables; un binding existente MUST NOT cambiar por mutaciones posteriores.
- `P5-REQ-004`: `ToolDefinition`, `ToolRequest` y `ToolResult` MUST ser inmutables, JSON-safe y no
  contener callables, objetos provider, exception causes, credenciales o valores sin sanitizar.

## Ejecución, permisos y fallos

- `P5-REQ-005`: `ToolExecutor` MUST resolver existencia, validar argumentos, verificar permisos y
  aprobación, ejecutar, validar output y construir un resultado neutral en ese orden.
- `P5-REQ-006`: Cada tool MUST declarar un permiso no vacío y un `SideEffect`; la autorización
  MUST usar coincidencia exacta y una tool desconocida/no permitida MUST NOT ejecutar el callable.
- `P5-REQ-007`: La aprobación MUST usar `ApprovalHandler` async y `ApprovalRequirement`; handler
  ausente, timeout, excepción o decisión inválida MUST producir denegación fail-closed.
- `P5-REQ-008`: El timeout de tool MUST ser 30 segundos salvo override positivo; aprobación MUST
  expirar a los 60 segundos salvo override. Cancelación MUST propagarse y liberar recursos.
- `P5-REQ-009`: `ToolRetryPolicy` MUST usar un intento total por defecto y permitir como máximo
  tres sólo para tools idempotentes; tools no idempotentes MUST ejecutar una sola vez.
- `P5-REQ-010`: El executor MUST deduplicar por `invocation_id` + `call_id`; duplicados concurrentes
  o posteriores MUST compartir resultado y no repetir efectos. El cache termina con la invocación.
- `P5-REQ-011`: `ToolFailurePolicy.RETURN_ERROR` MUST devolver fallos sanitizados al modelo;
  `RAISE` MUST elevar `ToolDeniedError`, `ToolExecutionError` o `RetryExhaustedError` sin filtrar la
  excepción original ni omitir cleanup.

## Bindings, perfiles y sesiones

- `P5-REQ-012`: `RuntimeModel.with_tools(registry, executor=...)` MUST devolver una vista inmutable
  y dejar intacto el modelo original; perfiles con host tools deshabilitadas MUST fallar antes de
  inferencia.
- `P5-REQ-013`: `Runtime.session()` y `resume_session()` MUST aceptar bindings opcionales para
  perfiles custom persistentes/híbridos tool-enabled. Resume MUST requerir un binding actual y
  MUST reemplazar metadata dinámica persistida, nunca confiar en ella como implementación.
- `P5-REQ-014`: `runtime.capabilities()` MUST reflejar soporte upstream; effective capabilities
  MUST intersectar provider, feature flag, profile, security policy y registry/executor válido.
- `P5-REQ-015`: `controlled_agent` MUST exponer sólo el registry host, mantener native tools
  deshabilitadas, `approval_mode=deny_all`, sandbox read-only y workspace vacío. El modelo MUST NOT
  recibir autoridad directa sobre callables o recursos del host.

## Eventos y observabilidad

- `P5-REQ-016`: El core MUST añadir eventos para approval requested/resolved, denied, failed y
  tool retry, conservando request/start/completed y orden causal exact-once por `call_id`.
- `P5-REQ-017`: Metadata de tools MUST contener sólo IDs y escalares operativos; argumentos,
  resultados y detalles permitidos MUST vivir en payload y respetar todos los payload modes,
  redacción, diagnostics y strict mode de Phase 4 en LangSmith y OpenTelemetry.

## Adapter Codex experimental

- `P5-REQ-018`: Codex dynamic tools MUST estar deshabilitadas por defecto y requerir
  `experimental_dynamic_tools=True` más capability `experimentalApi` confirmada antes de iniciar
  una invocación tool-enabled.
- `P5-REQ-019`: El adapter MUST mapear el snapshot neutral a `thread/start.dynamicTools`, atender
  `item/tool/call`, devolver content items compatibles y reconciliar `item/started`/`completed` sin
  exponer JSON-RPC o tipos Codex en APIs neutrales.
- `P5-REQ-020`: Formas, métodos o capability incompatibles MUST elevar `CapabilityError` antes de
  inferencia; el runtime MUST NOT degradar a parsing de prompts ni habilitar native tools.
- `P5-REQ-021`: Callables, permisos, aprobaciones, resultados, errores y caches MUST permanecer
  sólo en memoria host y MUST NOT persistirse en descriptors, config, rollout metadata, traces o
  provider raw. Sólo los schemas públicos mínimos MAY enviarse a Codex.

## Calidad y entrega

- `P5-REQ-022`: Fakes y tests unitarios/contractuales MUST cubrir el flujo completo sin red,
  credenciales ni cuota; la suite default MUST mantener cobertura branch-aware ≥90 %.
- `P5-REQ-023`: La release `0.6.0` MUST incluir ADR, documentación, ejemplo controlled-agent,
  lock y artefactos consistentes, y pasar gates locales más CI Linux/Windows 3.11–3.14.
- `P5-REQ-024`: El smoke Codex MUST ser separado y opt-in, usar un registry descartable,
  `gpt-5.6-luna`/`low`, demostrar al menos dos tool calls y registrar evidencia sanitizada.

## Estado de implementación

- `P5-REQ-001`–`P5-REQ-024`: `done`, con evidencia de hardening local y CI remoto posterior.

La revisión explícita del propietario fue otorgada en la solicitud actual; el paquete puede cerrar
tras registrar el commit de movimiento.
