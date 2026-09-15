# Validation Plan — Phase 5

## Pruebas focalizadas

Crear suites unitarias para:

- API neutral, enums, dataclasses, protocols e inmutabilidad;
- decorator, firmas, Pydantic adapters y schemas Draft 2020-12;
- registry, duplicados, orden, snapshot y aislamiento entre bindings;
- validación de arguments/output y serialización JSON-safe;
- permisos exactos y matriz side-effect/approval;
- aprobación exitosa, ausente, inválida, fallida, cancelada y expirada;
- timeout, retries idempotentes, no-retry no idempotente y exhaustion;
- deduplicación concurrente y cleanup del cache por invocación;
- return-error/raise y sanitización de excepciones;
- model/session bindings, profile gating y capabilities efectivas;
- eventos, payload modes, redacción, LangSmith fake y OTel in-memory;
- adapter Codex, dynamicTools, server requests y compatibilidad.

Comandos focalizados previstos:

```text
uv run pytest tests/unit/test_tools.py -q
uv run pytest tests/unit/test_tool_executor.py -q
uv run pytest tests/unit/test_tool_bindings.py -q
uv run --extra all pytest tests/unit/test_tool_observability.py -q
uv run pytest tests/unit/test_codex_dynamic_tools.py -q
```

Los tests podrán dividirse conservando estos owners de evidencia; todo cambio se refleja en
`07_traceability.md`.

## Contract tests y quota safety

Los contract tests deben demostrar:

- instalación/import base sin dependencias nuevas;
- core y tools neutrales sin provider/framework/exporter imports;
- `RuntimeModel`, `RuntimeSession`, `CodexRuntime` y `FakeRuntime` cumplen la nueva firma;
- parámetros opcionales mantienen compatibilidad con callers existentes;
- FakeRuntime ejecuta loops multi-tool deterministas y sesiones tool-enabled;
- JSON-safe event/result projection no filtra callables, causes o secretos;
- la suite default no lee credentials, abre sockets ni inicia Codex real.

```text
uv run --extra all pytest tests/contract/test_import_boundaries.py -q
uv run --extra all pytest tests/contract/test_public_api.py -q
uv run --extra all pytest tests/contract/test_protocols.py -q
uv run --extra all pytest tests/contract/test_quota_safety.py -q
uv run --extra all pytest tests -q
```

## Matrices obligatorias

### Registry y schemas

- tipos escalares, enums, optional, listas/mappings, dataclasses y Pydantic;
- defaults/required fields y validación de retorno;
- sync callable, variádicos, forward ref irresoluble y anotación ausente;
- nombre/descripción/permiso vacío, regex inválida, duplicate y schema inválido;
- snapshot previo/posterior a mutación y dos modelos independientes.

### Executor

- tool existente/inexistente y permiso exacto/prefijo/wildcard;
- los cuatro side effects por las tres approval requirements;
- handler approve/deny/ausente/timeout/raise/invalid;
- timeout default/override y cancelación externa;
- idempotent attempts 1/2/3 y no-idempotent reject;
- duplicado concurrente, duplicado terminal y call ID igual en otra invocation;
- arguments/output inválidos, callable raise y resultado no JSON-safe;
- return-error versus raise para cada clase de fallo.

### Runtime y provider

- profile × flag × provider capability × registry × executor;
- controlled-agent invoke/stream con uno y múltiples calls;
- custom persistent/hybrid create/resume y missing/replaced binding;
- shutdown/interrupt/cancel con server request pendiente;
- SDK compatible e incompatibilidades separadas de version/type/field/method/hook;
- ninguna ruta habilita native tools ni reenvía implementations.

### Observabilidad

- orden y exact-once de eventos por call;
- metadata canónica, payload modes e inmutabilidad;
- canaries en args/output/error/approval/descriptor;
- LangSmith run tree y OTel span/events/metrics;
- failure de exporter default/strict sin alterar tool semantics.

## Smoke Codex opt-in

```text
PROTEO_CODEX_DYNAMIC_TOOLS_INTEGRATION=1 \
uv run --extra all pytest tests/integration/codex_dynamic_tools -q -m integration
```

El smoke debe:

- seleccionar `level="low"` y afirmar resolución `gpt-5.6-luna`/`low`;
- crear un registry descartable con una tool read y una tool idempotente sin efecto externo;
- forzar una tarea que necesite al menos dos tool calls;
- comprobar argumentos validados, call IDs únicos, resultados y eventos;
- confirmar que native shell/write/network/browser/MCP permanecen denegados;
- cerrar runtime, handlers, futures y workspace;
- registrar sólo evidencia sanitizada.

Sin flag el smoke queda skipped. Falta de capability upstream bloquea `AC-P5-027`; no autoriza a
simular evidencia real ni a degradar a prompt parsing.

## Gates locales

```text
uv lock --check
uv run --extra all ruff format --check .
uv run --extra all ruff check .
uv run --extra all mypy src tests
uv run --extra all lint-imports
uv run --extra all pre-commit run --all-files
uv run --extra all pytest tests -q --cov=proteo_runtime --cov-branch --cov-report=term-missing --cov-fail-under=90
uv build
uv run python scripts/check_artifacts.py dist
python C:\Users\FAJ30\.codex\skills\encoding-guard\scripts\check_mojibake.py .
```

Todo function/method/helper nuevo debe tener docstring Google-style en inglés. Comentarios y
mensajes de commit también serán en inglés según `AGENTS.md`.

## Validación de packaging

Inspeccionar wheel y sdist y comprobar:

- versión `0.6.0` coherente en metadata, import y CLI;
- namespace tools y adapter experimental incluidos;
- cero dependencias runtime nuevas;
- instalación base importa contratos sin iniciar provider;
- los tipos JSON-RPC privados no aparecen en root exports;
- wheel y sdist instalados por separado ejecutan public API y fake smoke;
- README/ADR/ejemplo describen el mismo feature flag y safe defaults.

## Auditoría de seguridad y trazabilidad

Usar canaries credential-shaped en definitions, arguments, output, approval response, exception,
descriptor, metadata, payload y raw. Buscar cada canary en result/error, events proyectados,
diagnostics, LangSmith fake, OTel in-memory y artefactos persistidos. Debe haber cero coincidencias
fuera del payload `full` permitido; incluso `full` debe redactar secretos obligatorios.

Antes de mover el SDD:

- no queda ningún `P5-TASK-*`, `P5-REQ-*` o `AC-P5-*` pending/blocked;
- cada criterio referencia evidencia local, integración o CI;
- cada requisito aparece en tarea, criterio y matriz;
- no quedan handlers/futures/workspaces después de tests;
- guía, ADR, README y SDD no se contradicen;
- el movimiento conserva `phase-5-host-managed-tools`.

## Bloqueos conocidos

- El SDK 0.147.0 no ofrece una API estable completa para `item/tool/call`; el shim privado debe
  probar el hook real o bloquear el feature.
- Un runtime futuro puede reportar experimentalApi sin las formas esperadas; capability booleana
  sola no evita validación de compatibilidad.
- Cancelar un callable async no revierte efectos externos ya realizados; idempotencia y rollback
  de negocio pertenecen a la implementación host.
- Metadata dynamicTools persistida por Codex no prueba disponibilidad del callable y siempre debe
  reemplazarse al resume.
- Ausencia de subscription/capability sólo bloquea el smoke real; no debe romper la suite default.

## Evidencia inicial

- `.venv\Scripts\python.exe -m pytest -q`: `121 passed, 7 skipped`.
- `.venv\Scripts\ruff.exe check src tests`: verde.
- `.venv\Scripts\mypy.exe src\proteo_runtime`: verde en 46 archivos.
- `.venv\Scripts\lint-imports.exe`: 76 archivos, 292 dependencias, contrato conservado.

Esta evidencia corresponde al baseline pre-Phase 5 y no cambia criterios a `done`.

## Evidencia ejecutada — 2026-09-15

- `uv lock --check`: verde (`Resolved 82 packages`).
- Ruff format/check, mypy strict e import-linter: verdes; import-linter analizó 79 archivos y 325
  dependencias.
- Pre-commit (`ruff-format`, `ruff`, trailing whitespace, EOF, YAML y TOML): todos `Passed`.
- Suite default: `138 passed, 8 skipped`; cobertura branch-aware `90.11%`.
- `tests/contract/test_quota_safety.py`: `1 passed`; integración default: `7 skipped`, sin red,
  credenciales, subprocess Codex ni consumo de cuota.
- `python -m build --no-isolation` y `scripts/check_artifacts.py dist`: wheel y sdist `0.6.0`
  válidos. Se verificaron instalaciones aisladas base, sdist y extra LangGraph.
- Encoding guard sobre `src`, `tests`, `docs`, `examples`, `README.md`, `pyproject.toml` y
  `.github`: `CLEAN`.
- Smoke real separado: `PROTEO_CODEX_DYNAMIC_TOOLS_INTEGRATION=1 .venv\Scripts\python.exe -m
  pytest -q tests/integration/codex/test_dynamic_tools_smoke.py -s` → `1 passed in 15.44s`; se
  verificaron dos ejecuciones host-managed reales con outputs opacos, `gpt-5.6-luna`/`low` y
  registry descartable.
- CI remoto: [run 35027524386](https://github.com/fernan2cp/proteo-runtime/actions/runs/35027524386)
  `success`; jobs Ubuntu/Windows Python 3.11, 3.12, 3.13 y 3.14, calidad y packaging todos
  `success`.

La evidencia de este bloque habilita revisión, pero no autoriza por sí sola mover el paquete a
`complete/`.
