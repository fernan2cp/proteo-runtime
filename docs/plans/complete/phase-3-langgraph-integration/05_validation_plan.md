# Validation Plan — Phase 3

## Pruebas focalizadas

Crear tests unitarios para:

- selección de executor y validación del constructor;
- input/output keys, mappers, copias y excepciones;
- modelos de texto, Pydantic y JSON Schema;
- allowlist, namespace, inmutabilidad y rechazo de metadata insegura;
- envelope JSON, orden, terminal único y ausencia de value/raw/provider objects;
- EOF/terminal inválido, cancellation, `aclose()` y ausencia de tasks activos;
- descriptor ausente/inválido, model-mode rejection, resume/close exactos y no operaciones
  destructivas de sesión.

Ejecutar durante cada workstream:

```text
uv run --extra langgraph pytest tests/unit/test_langgraph_node.py -q
uv run --extra langgraph pytest tests/contract/test_langgraph_adapter.py -q
```

## StateGraph y quota safety

Los tests contractuales deben compilar StateGraphs reales con `FakeRuntime` para brain,
structured, custom streaming y sesión precreada. Deben ejecutar el stream v2 con modo `custom` y
comprobar tanto los chunks como el estado final.

La suite default conserva los guards existentes de procesos, red, credenciales y providers:

```text
uv run --extra langgraph pytest tests/contract/test_quota_safety.py -q
uv run --extra langgraph pytest tests -q
```

El smoke real se mantiene separado y opt-in:

```text
PROTEO_CODEX_INTEGRATION=1 uv run --extra langgraph pytest tests/integration/langgraph -q -m integration
```

Debe usar sólo threads/workspaces descartables creados por el test, cerrar handles y no borrar
sesiones ajenas.

Cada test que ejecute inferencia real debe afirmar `result.model == "gpt-5.6-luna"` y
`result.reasoning_effort == "low"`. El test de catálogo puede comprobar Terra/Sol sin iniciar
turnos; cualquier helper de smoke que no fuerce explícitamente `level="low"` es una falla de
validación.

## Gates locales

```text
uv lock --check
uv run --extra langgraph ruff format --check .
uv run --extra langgraph ruff check .
uv run --extra langgraph mypy src tests
uv run --extra langgraph lint-imports
uv run --extra langgraph pre-commit run --all-files
uv run --extra langgraph pytest tests -q --cov=proteo_runtime --cov-branch --cov-report=term-missing --cov-fail-under=90
uv build
uv run python scripts/check_artifacts.py dist
```

Todos los módulos y helpers nuevos deben tener docstrings Google-style en inglés. Los documentos
se escanean como UTF-8 con el guard de mojibake antes del cierre.

## Validación de packaging

Inspeccionar wheel y sdist y verificar:

- versión `0.4.0` coherente en metadata, import y CLI;
- paquete `proteo_runtime.integrations.langgraph` incluido;
- ninguna dependencia LangGraph en `Requires-Dist` sin extra marker;
- extras `langgraph` y `all` resolviendo el rango acordado;
- instalación base aislada importa core y Codex sin instalar/cargar LangGraph;
- instalación aislada con `[langgraph]` compila y ejecuta el ejemplo FakeRuntime;
- import de la integración sin extra ofrece el mensaje accionable.

## CI y evidencia de cierre

El workflow pasó en Linux y Windows para Python 3.11, 3.12, 3.13 y 3.14, incluyendo la suite con
extra, import-boundary y packaging. Run de implementación y cierre documental:
https://github.com/fernan2cp/proteo-runtime/actions/runs/34982580419.

Antes de mover el SDD:

- no queda ningún `P3-TASK-*`, `P3-REQ-*` o `AC-P3-*` pending/blocked;
- cada criterio debe nombrar evidencia local, integración autorizada o CI;
- el ejemplo no puede persistir objetos Codex en graph state;
- la matriz de `07_traceability.md` debe pasar la auditoría mecánica de IDs.

## Bloqueos conocidos

- Fallo del smoke real sin `PROTEO_CODEX_INTEGRATION=1` no es regresión: debe estar skipped.
- Falta de credenciales/servicio externo sólo bloquea evidencia opt-in, no la suite default.
- Incompatibilidad upstream con Python 3.14 es bloqueante para el criterio de salida y debe
  resolverse ajustando un rango compatible o documentando una decisión arquitectónica; no se
  ocultará excluyendo silenciosamente la celda.
