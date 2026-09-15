# Validation Plan — Phase 4

## Pruebas focalizadas

Crear suites unitarias para:

- observer protocol, bindings, config, status y lifecycle idempotente;
- fan-out, orden por invocación, concurrencia entre invocaciones y exact-once;
- `ainvoke()`/`astream()`/session/structured equivalentes y terminal único;
- matriz de payload modes, redacción recursiva, inmutabilidad y descriptor hashing;
- dispatch/timeout/flush/close failures en default y strict mode;
- LangSmith run hierarchy, parent LangGraph, terminales y cliente falso;
- OTel spans, metrics, ownership y cardinalidad con SDK in-memory;
- Codex-native launch config, capability gating, privacidad y equivalencia semántica.

Comandos focalizados previstos:

```text
uv run pytest tests/unit/test_observability.py -q
uv run --extra langsmith pytest tests/unit/test_langsmith_observer.py -q
uv run --extra otel pytest tests/unit/test_opentelemetry_observer.py -q
uv run pytest tests/unit/test_codex_native_otel.py -q
uv run --extra all pytest tests/contract/test_observability.py -q
```

Los nombres podrán dividirse en más archivos manteniendo estos owners de evidencia; cualquier
cambio debe reflejarse en `07_traceability.md`.

## Contract tests y quota safety

Los contract tests deben demostrar:

- instalación/import base sin SDKs opcionales;
- import errors accionables por extra;
- core sin imports externos/proveedor/framework;
- `Runtime`, `RuntimeResult`, `FakeRuntime` y adapters cumplen la nueva superficie;
- StateGraph real con FakeRuntime produce hierarchy/correlación sin objetos provider;
- ningún test default lee variables credential-shaped, abre sockets o inicia Codex real.

```text
uv run --extra all pytest tests/contract/test_import_boundaries.py -q
uv run --extra all pytest tests/contract/test_public_api.py -q
uv run --extra all pytest tests/contract/test_protocols.py -q
uv run --extra all pytest tests/contract/test_langgraph_adapter.py -q
uv run --extra all pytest tests/contract/test_quota_safety.py -q
uv run --extra all pytest tests -q
```

## Smokes externos opt-in

Separar flags para que autorizar uno no habilite los demás accidentalmente:

```text
PROTEO_LANGSMITH_INTEGRATION=1 uv run --extra all pytest tests/integration/langsmith -q -m integration
PROTEO_OTEL_INTEGRATION=1 uv run --extra all pytest tests/integration/opentelemetry -q -m integration
PROTEO_CODEX_NATIVE_OTEL_INTEGRATION=1 uv run --extra all pytest tests/integration/codex_native_otel -q -m integration
```

Cada test de inferencia real debe seleccionar explícitamente `level="low"` y afirmar
`gpt-5.6-luna`/`low`. Los smokes usan proyectos/collectors/workspaces descartables, sanitizan la
evidencia y cierran runtimes/providers propios. No archivan ni borran sesiones ajenas.

Evidencia mínima:

- LangSmith: run hierarchy visible, metadata-only y parent LangGraph cuando corresponda;
- Proteo OTel: spans/métricas recibidos por collector con IDs correlacionados;
- Codex-native: habilitación capability-gated, `log_user_prompt=false` y resultado idéntico sin
  exigir `trace_id` compartido.

Falta de credenciales o collector sólo bloquea el smoke correspondiente. No permite marcar su
criterio como `done` sin evidencia alternativa autorizada.

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
```

Todo function/method/helper nuevo debe tener docstring Google-style en inglés. Ejecutar el guard de
mojibake sobre los documentos antes del cierre.

## Validación de packaging

Inspeccionar wheel y sdist y comprobar:

- versión `0.5.0` coherente en metadata, import y CLI;
- módulos neutrales y adapters oficiales incluidos;
- `langsmith` y `opentelemetry-api` aparecen sólo con markers de extras;
- OTel SDK no es dependencia runtime de wheel/sdist;
- `[all]` incluye LangGraph, LangSmith y OTel;
- instalación base no instala/carga opcionales;
- instalaciones `[langsmith]`, `[otel]` y `[all]` importan sólo sus superficies;
- import/config sin extra produce el mensaje accionable correcto.

## Auditoría de seguridad y trazabilidad

Ejecutar tests con canaries credential-shaped en metadata, payload, texto, exception causes,
headers, descriptors y raw. Buscar los canaries en todo output fake/in-memory, diagnostics y
capturas. Cero coincidencias es obligatorio en `metadata_only`, `redacted` y campos siempre
protegidos de `full`.

Antes de mover el SDD:

- no queda ningún `P4-TASK-*`, `P4-REQ-*` o `AC-P4-*` pending/blocked;
- cada criterio referencia evidencia local, integración autorizada o CI;
- cada requisito aparece en tarea, criterio y matriz;
- cada tarea referencia IDs existentes;
- el README público y la guía no contradicen la implementación;
- el movimiento conserva el nombre del paquete.

## Bloqueos conocidos

- Smoke sin su flag debe quedar skipped y no es regresión.
- Un provider OTel global no configurado puede producir spans no recording; el test in-memory debe
  inyectar providers explícitos y no depender del estado global del runner.
- Ausencia de propagación upstream sólo permite `correlation_supported=False`; no se aceptan IDs
  inventados.
- Incompatibilidad de un extra en Python 3.11–3.14 bloquea release y no se oculta eliminando una
  celda de CI.

## Evidencia ejecutada en este workstream

- `.venv\Scripts\python.exe -m pytest -q`: `121 passed, 7 skipped`.
- `.venv\Scripts\python.exe -m pytest --cov=proteo_runtime --cov-branch`: `90.11%`; el gate
  configurado de `90%` queda satisfecho localmente, pendiente de confirmación en CI.
- `.venv\Scripts\ruff.exe check src tests`, `.venv\Scripts\mypy.exe src\proteo_runtime` y
  `.venv\Scripts\lint-imports.exe`: verdes.
- `.venv\Scripts\pre-commit.exe run --all-files`: verde.
- `uv lock` y `uv build`: lock actualizado; wheel y sdist `0.5.0` construidos.
- Instalación aislada sin dependencias de wheel y sdist en `.ci-wheel-venv` y `.ci-sdist-venv`:
  ambas importan `proteo_runtime` en versión `0.5.0`.
- `test_otel_sdk_in_memory_export_is_supported_when_dev_extra_is_installed`: passed con
  `opentelemetry-sdk==1.44.0`, sin collector ni provider global.
- Smokes LangSmith/OTLP/Codex-native y CI remoto no se ejecutaron por falta de autorización,
  credenciales/collector y conexión CI; permanecen pendientes.
