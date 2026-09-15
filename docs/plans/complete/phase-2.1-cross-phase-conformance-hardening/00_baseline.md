# Baseline

- Commit auditado: `8dfd4ff`.
- Versión: `0.3.0`.
- Rama de trabajo: `codex/phase-2-1-cross-phase-conformance-hardening`.
- Worktree al iniciar: limpio.
- Evidencia previa: `60 passed, 4 skipped`, coverage reportada `90.12%`, Ruff, mypy e
  import-linter; esa evidencia es histórica y no prueba este hardening.

## Componentes afectados

- `src/proteo_runtime/core/{input,model,profiles}.py`.
- `src/proteo_runtime/providers/codex/{runtime,_runner,_structured}.py`.
- `src/proteo_runtime/config/*.py` y `src/proteo_runtime/testing/fakes.py`.
- Tests unitarios, contractuales e integración Codex opt-in.

## Gaps confirmados

Los hallazgos F0-01, F0-03, F0-04; F1-07 a F1-12; y F2-15 a F2-28 requieren corrección o
prueba nueva. F0-02 requiere alinear la guía con `RuntimeIdentity`. F0/F1/F2 históricos no se
reabren; sus erratas se añadirán como referencia append-only.

## Riesgos y decisiones cerradas

- No se confiará en permisos/contexto contenidos en un descriptor.
- No habrá fallback de catálogo ni inferencias reales para cada mapping.
- Un fallo de catálogo, terminal o cleanup será fail-closed.
- La migración conservará proveedor, identidad, thread e historia.
