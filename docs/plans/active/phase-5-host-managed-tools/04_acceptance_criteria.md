# Acceptance Criteria — Phase 5

Todos los criterios comienzan en estado `pending`.

- `AC-P5-001`: Una instalación base importa `proteo_runtime.tools` y core/Codex sin dependencias
  nuevas ni imports de frameworks/exporters/provider desde el namespace neutral. Requisitos:
  `P5-REQ-001`. Tareas: `P5-TASK-0001`, `P5-TASK-0007`.
- `AC-P5-002`: El namespace exporta exactamente los contratos documentados, todos inmutables o
  protocols según diseño, y public API/import-linter permanecen verdes. Requisitos: `P5-REQ-001`,
  `P5-REQ-004`. Tareas: `P5-TASK-0001`, `P5-TASK-0007`.
- `AC-P5-003`: El decorator genera schemas válidos para tipos soportados y rechaza sync,
  variádicos, anotaciones ausentes, tipos no representables, nombres inválidos y schema inválido
  antes de registrar. Requisitos: `P5-REQ-002`. Tareas: `P5-TASK-0001`, `P5-TASK-0007`.
- `AC-P5-004`: Duplicados fallan; orden y snapshots son deterministas e inmutables; mutar el
  registry no cambia modelos/sesiones ya enlazados. Requisitos: `P5-REQ-003`. Tareas:
  `P5-TASK-0001`, `P5-TASK-0007`.
- `AC-P5-005`: Definitions, requests y results son JSON-safe y no contienen callables, SDK
  objects, tracebacks, causes, secretos ni `repr()` arbitrario. Requisitos: `P5-REQ-004`,
  `P5-REQ-021`. Tareas: `P5-TASK-0001`, `P5-TASK-0004`, `P5-TASK-0005`, `P5-TASK-0007`.
- `AC-P5-006`: Arguments se validan/coercionan según schema antes de ejecutar y output se valida y
  serializa después; failures no ejecutables no llaman al callable. Requisitos: `P5-REQ-005`.
  Tareas: `P5-TASK-0002`, `P5-TASK-0007`.
- `AC-P5-007`: Tool inexistente, permiso no exacto o permission policy vacía deniega sin ejecución;
  prefijos y wildcards no conceden autoridad. Requisitos: `P5-REQ-006`. Tareas:
  `P5-TASK-0002`, `P5-TASK-0007`.
- `AC-P5-008`: `never`, `always` y `for_side_effects` solicitan u omiten aprobación exactamente
  según definición; sólo `APPROVE` permite ejecutar. Requisitos: `P5-REQ-007`. Tareas:
  `P5-TASK-0002`, `P5-TASK-0007`.
- `AC-P5-009`: Handler ausente, timeout de 60 s, excepción, cancelación interna o retorno inválido
  produce denegación sanitizada y cero ejecuciones. Requisitos: `P5-REQ-007`, `P5-REQ-008`.
  Tareas: `P5-TASK-0002`, `P5-TASK-0007`.
- `AC-P5-010`: Timeout efectivo de 30 s/override y cancelación externa terminan futures/locks,
  liberan el cache y no dejan ejecución administrada pendiente. Requisitos: `P5-REQ-008`. Tareas:
  `P5-TASK-0002`, `P5-TASK-0006`, `P5-TASK-0007`.
- `AC-P5-011`: Una tool no idempotente se ejecuta una vez aunque configure más intentos; la
  configuración incompatible falla antes de ejecución. Requisitos: `P5-REQ-009`. Tareas:
  `P5-TASK-0002`, `P5-TASK-0007`.
- `AC-P5-012`: Una tool idempotente ejecuta como máximo tres intentos, emite un retry por intento
  posterior y produce `RetryExhaustedError`/resultado final correcto. Requisitos: `P5-REQ-009`,
  `P5-REQ-011`. Tareas: `P5-TASK-0002`, `P5-TASK-0007`.
- `AC-P5-013`: Requests duplicados por invocation/call ID comparten exactamente un resultado y una
  ejecución; `RETURN_ERROR` continúa y `RAISE` eleva el error Proteo esperado tras cleanup.
  Requisitos: `P5-REQ-010`, `P5-REQ-011`. Tareas: `P5-TASK-0002`, `P5-TASK-0006`,
  `P5-TASK-0007`.
- `AC-P5-014`: `with_tools()` devuelve una vista nueva, conserva el modelo original y rechaza
  brain/structured/session/native o custom profiles incompatibles antes de inferencia. Requisitos:
  `P5-REQ-012`. Tareas: `P5-TASK-0003`, `P5-TASK-0007`.
- `AC-P5-015`: Provider y effective capabilities difieren correctamente para combinaciones de
  soporte, flag, profile, security policy, registry vacío y executor incompatible. Requisitos:
  `P5-REQ-014`. Tareas: `P5-TASK-0003`, `P5-TASK-0007`.
- `AC-P5-016`: Un custom profile persistente/híbrido tool-enabled crea sesión con snapshot actual y
  ejecuta múltiples calls sin duplicar contexto host/runtime. Requisitos: `P5-REQ-013`. Tareas:
  `P5-TASK-0003`, `P5-TASK-0006`, `P5-TASK-0007`.
- `AC-P5-017`: Resume tool-enabled sin binding falla antes de provider access; con binding reemplaza
  definitions persistidas y una sesión sin tools envía lista vacía. Requisitos: `P5-REQ-013`,
  `P5-REQ-021`. Tareas: `P5-TASK-0003`, `P5-TASK-0006`, `P5-TASK-0007`.
- `AC-P5-018`: Controlled-agent conserva approval deny-all, sandbox read-only y workspace vacío;
  shell, write, network, browser, MCP y native tools siguen inaccesibles. Requisitos:
  `P5-REQ-015`. Tareas: `P5-TASK-0003`, `P5-TASK-0006`, `P5-TASK-0007`.
- `AC-P5-019`: Cada call produce secuencia causal exact-once para success, approval, denial,
  failure y retry; invoke/stream observan el mismo terminal y usage cuenta calls/retries.
  Requisitos: `P5-REQ-016`. Tareas: `P5-TASK-0004`, `P5-TASK-0007`.
- `AC-P5-020`: Metadata contiene sólo escalares canónicos y payload modes excluyen/redactan/incluyen
  arguments/results según Phase 4, sin mutar eventos originales. Requisitos: `P5-REQ-017`,
  `P5-REQ-021`. Tareas: `P5-TASK-0004`, `P5-TASK-0007`.
- `AC-P5-021`: LangSmith fake y OTel in-memory representan un tool child/span por call, con
  approval/retry/failure correctos y sin IDs de alta cardinalidad en metric labels. Requisitos:
  `P5-REQ-017`. Tareas: `P5-TASK-0004`, `P5-TASK-0007`.
- `AC-P5-022`: Sin feature flag una vista tool-enabled falla cerrada; con flag y capability ausente
  falla antes de iniciar inferencia; sólo ambos habilitan host tools. Requisitos: `P5-REQ-018`.
  Tareas: `P5-TASK-0005`, `P5-TASK-0007`.
- `AC-P5-023`: El doble de App Server observa dynamicTools en start/resume y el ciclo completo
  started→server request→response→completed para éxito, denegación y error. Requisitos:
  `P5-REQ-019`. Tareas: `P5-TASK-0005`, `P5-TASK-0006`, `P5-TASK-0007`.
- `AC-P5-024`: Versión, type, field, method o message-router hook incompatible produce
  `CapabilityError` pre-inference y nunca activa prompt parsing/native tools. Requisitos:
  `P5-REQ-020`. Tareas: `P5-TASK-0005`, `P5-TASK-0007`.
- `AC-P5-025`: Descriptors, config, rollout/traces/diagnostics/provider raw no contienen callables,
  permisos, aprobaciones, outputs, caches o secretos; handlers pendientes siempre se retiran.
  Requisitos: `P5-REQ-021`. Tareas: `P5-TASK-0004`, `P5-TASK-0005`, `P5-TASK-0006`,
  `P5-TASK-0007`.
- `AC-P5-026`: Suite default usa fakes/in-memory, no lee credenciales, abre red ni consume cuota, y
  mantiene cobertura branch-aware ≥90 %. Requisitos: `P5-REQ-022`. Tareas: `P5-TASK-0007`,
  `P5-TASK-0008`, `P5-TASK-0009`.
- `AC-P5-027`: Smoke opt-in Luna/low completa una invocación con al menos dos tool calls, demuestra
  ejecución host-only y elimina todos los recursos descartables. Requisitos: `P5-REQ-024`.
  Tareas: `P5-TASK-0008`, `P5-TASK-0009`.
- `AC-P5-028`: ADR, README/API docs, ejemplo, versión `0.6.0`, lock, wheel/sdist, instalaciones
  aisladas, gates y CI Linux/Windows 3.11–3.14 son consistentes antes del cierre. Requisitos:
  `P5-REQ-023`. Tareas: `P5-TASK-0008`, `P5-TASK-0009`.

## Estado de aceptación

- `AC-P5-001`, `AC-P5-002`, `AC-P5-004` y `AC-P5-007`: `done`, conservan evidencia válida.
- `AC-P5-003`, `AC-P5-005`, `AC-P5-006` y `AC-P5-008`–`AC-P5-028`:
  `in_progress — audit remediation pending`; deben verificarse nuevamente después del hardening.

La revisión explícita del propietario sigue pendiente para cerrar el SDD y mover el paquete.
