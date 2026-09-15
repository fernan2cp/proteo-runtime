# Rollout and Rollback — Phase 4

## Secuencia de entrega

1. Añadir contratos neutrales, bus, health y tests sin exporters.
2. Integrar metadata/payload/redacción y correlación en fakes y runner Codex.
3. Conectar lifecycle, models, structured output y sessions al bus único.
4. Añadir extra y observer LangSmith con cliente falso.
5. Añadir extra y observer OpenTelemetry con SDK in-memory.
6. Añadir configuración Codex-native OTel capability-gated.
7. Completar contract tests, StateGraph, documentación y ejemplos.
8. Actualizar a `0.5.0`, lock, artefactos e instalaciones aisladas.
9. Ejecutar smokes opt-in, CI final y registrar evidencia. El movimiento a `complete/` requiere
   además la revisión y confirmación explícita del propietario; este trabajo lo deja en `active/`.

Cada paso debe mantener la suite default sin red/cuota y conservar el import boundary del core.

## Compatibilidad

- La fase es aditiva para callers que no pasan `observability` ni `codex_native_otel`.
- Sin observers, el comportamiento es el de `0.4.0` y status es `disabled`.
- `RuntimeEvent`/`RuntimeResult` añaden campos con defaults para conservar construcción existente.
- La ampliación de `Runtime` exige actualizar implementaciones estructurales y fakes en la misma
  release pre-1.0; se documentará en notas de `0.5.0`.
- `RuntimeNode` no cambia sus parámetros ni ownership de sesión.
- Extras opcionales no llegan a la instalación base.
- Descriptors `prt1.*`, config JSON v1, provider history y model mappings no migran.
- `metadata_only` es default aun cuando un SDK externo tenga tracing global habilitado; el adapter
  Proteo controla su propio payload.

## Feature containment

El host puede desplegar en este orden:

- event bus con zero observers;
- un observer metadata-only en modo no estricto;
- segundo observer y correlación cruzada;
- strict mode sólo en entornos que acepten fallar por telemetría;
- Codex-native OTel en un runtime separado/canary antes de habilitación general.

Cambiar payload a `redacted` o `full` requiere configuración explícita por binding. No existe
escalado automático de payload mode ni fallback de strict a non-strict.

## Rollback de aplicación

Una aplicación puede retirar todos los bindings y volver a status `disabled` sin cambiar modelos,
sesiones o graph state. También puede retirar un solo exporter manteniendo el otro porque no hay
dependencia entre ellos.

Para contener un exporter defectuoso antes de revertir código, usar modo no estricto y binding
`disabled`. Codex-native OTel se desactiva retirando su opt-in y reiniciando sólo el runtime que
Proteo posee; nunca se reescriben configuraciones globales del usuario.

## Rollback de código

Revertir commits en orden inverso y mantener juntos:

- release/docs/artifacts `0.5.0`;
- Codex-native config y sus tests;
- cada observer, su extra, lock y tests;
- runtime dispatch más terminal enrichment;
- payload/redaction/correlation;
- contratos neutrales/event bus.

Una reversión no debe eliminar telemetry externa ya enviada, tocar credenciales, modificar config
global de Codex ni borrar sesiones. Si se vuelve a `0.4.0`, callers deben retirar los argumentos y
contratos públicos de Phase 4 antes del downgrade.

## Contención de fallos

- Observer timeout/failure degrada sólo observabilidad en modo default.
- Strict mode falla explícitamente después del cleanup.
- Cancelación del host conserva precedencia sobre errores de exporter.
- Parent LangGraph inválido crea raíz Proteo segura.
- Provider OTel ausente produce guía de instalación, no import failure del paquete base.
- Capability Codex-native ausente falla antes de inferencia si el usuario pidió el opt-in.
- Nunca se reintenta una inferencia por fallo de exporter.
- Ningún rollback eleva payload mode o habilita telemetría nativa implícitamente.

## Criterio de go/no-go

La release sólo avanza si `AC-P4-001`–`AC-P4-028` están `done`, todos los gates e instalaciones
aisladas pasan, CI Linux/Windows está verde y existe evidencia sanitizada del exit criterion. Un
fallo de privacidad, duplicación de terminales, pérdida de cleanup o contaminación de la
instalación base es `no-go` absoluto.
