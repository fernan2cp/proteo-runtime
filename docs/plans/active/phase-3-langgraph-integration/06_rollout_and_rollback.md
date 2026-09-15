# Rollout and Rollback — Phase 3

## Secuencia de entrega

1. Añadir extras, lock, namespace e import guards sin conectar ejecución.
2. Implementar state mapping y structured pass-through con fakes.
3. Implementar metadata allowlisted y pruebas de seguridad/inmutabilidad.
4. Implementar custom streaming, terminal result y cancelación.
5. Implementar resume-only sessions y cleanup exhaustivo.
6. Añadir StateGraph contracts, ejemplo, documentación y smoke Codex opt-in.
7. Actualizar a `0.4.0`, construir artefactos, validar installs y completar CI.
8. Registrar evidencia, cerrar IDs y mover este paquete a `docs/plans/complete/`.

Cada paso debe conservar la suite default sin cuota, el import del paquete base sin LangGraph y
los contratos directos de Phase 0–2.1.

## Compatibilidad

- `proteo_runtime.__all__`, APIs core y `CodexRuntime` existentes no cambian.
- LangGraph sólo se instala al pedir `[langgraph]` o `[all]`.
- Los usuarios directos no reciben callbacks, metadata ni cambios de lifecycle implícitos.
- Los descriptors `prt1.*` no cambian de formato y el nodo delega toda validación a
  `resume_session()`.
- No hay migraciones de datos, sesiones, configuración JSON ni provider history.
- Phase 3 es aditiva y se publica como `0.4.0` por introducir una superficie pública pre-1.0.

## Rollback de aplicación

Una aplicación puede retirar `RuntimeNode` y volver a invocar `RuntimeModel` o `RuntimeSession`
directamente. Debe conservar externamente sus descriptors; quitar el adaptador nunca archiva ni
borra historia.

Si falla streaming custom, el host puede consumir sólo el update final mediante la API directa
mientras se revierte la integración. No se añadirá un fallback silencioso de `astream()` a
`ainvoke()` porque perdería el contrato de streaming/cancelación.

## Rollback de código

Revertir commits en orden inverso y mantener juntos:

- proyección de eventos, terminal handling y tests;
- sesión resume-only, cleanup y tests;
- módulo de integración, extras, lock y packaging tests;
- versión/documentación/artefactos de `0.4.0`.

La reversión no debe modificar core para simular LangGraph, reescribir descriptors ni eliminar
threads/workspaces no creados por tests.

## Contención de fallos

- Metadata o state inválido falla antes del provider.
- Descriptor inválido falla antes de ejecutar un turno.
- Error del runtime afecta sólo el nodo actual y conserva su excepción neutral.
- Error del output mapper ocurre después de la inferencia, pero igualmente cierra stream/session.
- Cancelación conserva `CancelledError` y no deja trabajo silencioso.
- Error de cleanup nunca convierte un turno fallido en success.
- Un import sin extra no rompe el paquete base y explica cómo habilitar la integración.
