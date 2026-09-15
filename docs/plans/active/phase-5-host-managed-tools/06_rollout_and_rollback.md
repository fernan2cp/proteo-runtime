# Rollout and Rollback — Phase 5

## Estrategia de entrega

La fase se entrega incrementalmente detrás de safe defaults:

1. incorporar contratos, schemas, registry y executor sin conectarlos a Codex;
2. integrar fakes, bindings y observabilidad manteniendo host tools efectivas en false;
3. incorporar el adapter Codex experimental y compatibility checks;
4. habilitar tests simulados con flag explícito y provider double;
5. ejecutar smoke real opt-in con tools sin efecto externo;
6. documentar ADR/API/ejemplo, actualizar versión y construir artefactos;
7. completar CI, evidencia, revisión y movimiento del SDD.

La mera instalación de `0.6.0` no activa dynamic tools. Callers existentes que no usan
`with_tools()`, registry/executor o parámetros de sesión nuevos conservan comportamiento `0.5.0`.

## Gates de activación

- **Gate A — Neutral contracts:** schemas, registry y executor pasan unit/contract tests sin
  provider imports ni dependencias nuevas.
- **Gate B — Authority boundary:** matrices de permisos, aprobación, retries, dedupe, cancellation
  y no-leak demuestran ejecución host-only.
- **Gate C — Runtime integration:** profiles, sessions, capabilities, events y exporters pasan con
  fakes y App Server doubles.
- **Gate D — Experimental compatibility:** SDK/runtime fijado soporta initialize opt-in,
  dynamicTools y server-request hook exactos; incompatibilidades fallan pre-inference.
- **Gate E — Real smoke:** Luna/low completa al menos dos calls descartables y cleanup total.
- **Gate F — Release:** cobertura ≥90 %, gates, build, instalaciones aisladas y CI multi-OS verdes.

Un gate fallido bloquea los posteriores que dependan de él. Ningún fallo autoriza a relajar
permission checks, habilitar native tools o introducir prompt parsing.

## Compatibilidad

- `RuntimeModel.with_tools()` es aditivo; firmas existentes conservan defaults.
- `session()`/`resume_session()` reciben keyword-only opcionales; llamadas actuales siguen válidas.
- `RuntimeCapabilities` conserva sus campos y significado provider/effective documentado.
- Nuevos `RuntimeEventKind` son aditivos; consumers exhaustivos deben actualizarse y el cambio se
  documenta en notas de `0.6.0`.
- No cambia config schema v1, model mappings, session descriptor v1 ni identidad.
- No cambia el comportamiento de brain, structured, session built-in o native.
- `openai-codex` permanece dentro del rango fijado hasta completar la matriz de compatibilidad; un
  cambio de rango requiere reabrir requisitos, tests y smoke.

## Feature flag y degradación

`experimental_dynamic_tools` es false por defecto. Si está false, ninguna definition se envía y
effective host tools es false. Si está true pero falla capability/compatibilidad, una invocación
tool-enabled falla con `CapabilityError` antes de inferencia; las invocaciones sin tools continúan
sin cambios.

No existe degradación automática de tool-enabled a modelo sin tools porque alteraría semántica y
podría ocultar una pérdida de control. El host decide si reintenta con otra ruta.

## Rollback

### Antes de release

- revertir el workstream defectuoso preservando este SDD y su evidencia;
- mantener el flag apagado y host tools efectivas en false;
- reabrir task/criteria afectados y corregir el mismo diseño si cambia un contrato.

### Después de release

- mitigación inmediata: deshabilitar `experimental_dynamic_tools` en la construcción del runtime;
- callers vuelven a perfiles sin binding o a `0.5.x` si no dependen de public symbols nuevos;
- no se borran ni migran sesiones automáticamente;
- al resumir una sesión previamente tool-enabled con feature apagado, enviar lista vacía o fallar
  explícitamente antes de resume según capability disponible;
- emitir patch `0.6.x` para defectos contractuales compatibles; un cambio incompatible exige una
  decisión versionada y actualización del SDD/ADR.

El rollback no puede deshacer efectos de negocio ya confirmados por callables. Cada aplicación es
responsable de idempotency keys durables y compensación fuera del cache por invocación de Proteo.

## Evidencia de release

Registrar en este SDD:

- commit inicial y final;
- versiones Python, SDK y runtime probadas;
- resultados de suites focalizadas, gates y cobertura;
- artifact names/hashes e instalaciones aisladas;
- resultado sanitizado del smoke Luna/low;
- URLs y matriz de CI Linux/Windows 3.11–3.14;
- revisión explícita del propietario;
- commit que mueve el paquete a `docs/plans/complete/`.

La release y el cierre sólo avanzan cuando `P5-REQ-001`–`P5-REQ-024`,
`P5-TASK-0001`–`P5-TASK-0009` y `AC-P5-001`–`AC-P5-028` están `done` con evidencia.

## Estado de entrega

La rama `arch/phase-5-host-managed-tools` está publicada con `0.6.0`, commits granulares y CI
remoto verde en el run
[35025491793](https://github.com/fernan2cp/proteo-runtime/actions/runs/35025491793). El release
queda listo para revisión del propietario; `P5-TASK-0009` permanece
`in_progress — owner review pending` y no se ha movido la carpeta.
