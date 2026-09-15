# Technical Design — Phase 5

## Límite arquitectónico

La dependencia conserva esta dirección:

```text
application callable
       │
       ▼
proteo_runtime.tools ──> core contracts / observability contracts
       ▲
       │ neutral request/result
provider adapter
       │
       └── Codex experimental adapter ──> private App Server shim
```

`proteo_runtime.tools` no importa providers, LangGraph, LangSmith u OpenTelemetry. El core y los
fakes pueden depender de sus contratos neutrales. Sólo el adapter experimental conoce
`dynamicTools`, `item/tool/call` y tipos generados del SDK.

## API pública neutral

El namespace expondrá, sin reexportar automáticamente todo desde el paquete raíz:

```python
class SideEffect(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ApprovalRequirement(StrEnum):
    NEVER = "never"
    ALWAYS = "always"
    FOR_SIDE_EFFECTS = "for_side_effects"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    DENY = "deny"


class ToolFailurePolicy(StrEnum):
    RETURN_ERROR = "return_error"
    RAISE = "raise"


@dataclass(frozen=True, slots=True)
class ToolRetryPolicy:
    max_attempts: int = 1


@dataclass(frozen=True, slots=True)
class ToolPermissionPolicy:
    allowed_permissions: frozenset[str]


class ApprovalHandler(Protocol):
    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision: ...
```

`ToolRetryPolicy` acepta `1..3`. Un executor rechaza `max_attempts > 1` si la definición no es
idempotente. No incorpora delay, backoff ni jitter en esta fase.

`ToolPermissionPolicy` normaliza una copia inmutable, rechaza strings vacíos y compara permisos
literalmente. `"customer.read"` no implica `"customer.*"`, jerarquía ni autorización de otro
permiso.

## Definición y decorator

`ToolDefinition` contiene:

```text
name
description
input_schema
output_schema
permission
side_effect
idempotent
approval
timeout_seconds
```

El nombre usa el subset portable `^[A-Za-z_][A-Za-z0-9_-]{0,63}$`. Descripción y permiso son
obligatorios y no vacíos. `timeout_seconds`, cuando existe, debe ser finito y positivo.

`runtime_tool(...)` recibe metadata y decora sólo `async def`. Construye schemas con las
anotaciones resueltas por `typing.get_type_hints()` y Pydantic:

- cada parámetro público se convierte en un campo de un modelo de entrada;
- defaults y optionalidad se preservan;
- `*args`, `**kwargs`, parámetros sin anotación y tipos no representables se rechazan;
- la anotación de retorno es obligatoria y genera el schema de salida;
- ambos schemas se validan como Draft 2020-12 antes de registrar;
- el wrapper conserva nombre, docstring, firma y referencia privada al callable.

El callable vive únicamente en un binding privado del registro. `ToolDefinition` y el schema que
ve el provider nunca incluyen el objeto ejecutable.

## ToolRegistry y snapshots

El registro ofrece `register()`, `get()`, `definitions()` y `snapshot()`. Registrar dos nombres
iguales falla aunque apunten al mismo callable. `definitions()` conserva orden de inserción y
devuelve valores inmutables.

`snapshot()` copia definitions más bindings privados en una vista read-only. `with_tools()` y las
sesiones capturan ese snapshot; registrar o quitar tools después no altera ejecuciones ya creadas.
El provider recibe sólo las definitions serializadas del snapshot.

## Requests, resultados y contexto de ejecución

`ToolRequest` contiene `invocation_id`, `call_id`, `name`, arguments inmutables y los IDs
session/turn disponibles. `ApprovalRequest` añade permission, side effect y arguments validados.

`ToolResult` contiene:

```text
invocation_id        call_id             tool_name
success              output              error_code
attempts             duration_ms         denied
timed_out
```

`output` es un valor JSON-safe validado contra el schema de retorno. En fallo contiene sólo un
mensaje acotado y estable apto para el modelo; exception message/cause, traceback y objetos
arbitrarios no se copian. Los detalles sensibles sólo pueden aparecer en payload interno sujeto a
redacción, nunca en metadata ni diagnostics.

## Pipeline de ToolExecutor

El executor recibe registry, permission policy, approval handler opcional, retry policy, failure
policy, timeout default y approval timeout. El orden es fijo:

```text
deduplicate call_id
  → resolve definition
  → validate arguments
  → exact permission check
  → approval decision
  → execute with timeout
  → validate/serialize output
  → build ToolResult
  → resolve duplicate waiters
```

Existencia, schema, permiso y aprobación se resuelven antes de invocar el callable. Cada etapa
emite el evento neutral correspondiente. El callable se invoca con los argumentos validados, no
con el mapping provider original.

Sólo un owner ejecuta una clave `(invocation_id, call_id)`. Duplicados aguardan el mismo future y
reciben el mismo objeto terminal. El cache y futures se eliminan al finalizar la invocación; el
executor no ofrece idempotencia durable entre procesos.

Por default las llamadas se serializan por invocación para conservar orden y simplificar efectos.
Invocaciones distintas pueden ejecutar tools concurrentemente. No se expone configuración de
paralelismo en Phase 5.

## Aprobación

`never` omite HITL. `always` solicita aprobación. `for_side_effects` solicita aprobación para
`write` y `destructive`, y la omite para `none` y `read`.

El handler se ejecuta bajo `asyncio.timeout(approval_timeout_seconds)`. Sólo el enum
`ApprovalDecision.APPROVE` concede ejecución. Handler ausente, retorno distinto, excepción,
cancelación interna o timeout genera `ToolDeniedError`/resultado denied según failure policy. La
cancelación de la invocación externa conserva la cancelación y ejecuta cleanup; no se transforma
en una denegación ordinaria.

## Timeout, retries y fallos

El timeout efectivo es el override de `ToolDefinition` o 30 segundos. Se aplica a cada intento.
Timeout y excepción del callable son candidatos a retry sólo cuando `idempotent=True` y
`max_attempts > 1`. Fallos previos a ejecución y output inválido no reejecutan la tool. Cada retry
emite `TOOL_RETRY_SCHEDULED` antes del siguiente intento.

Tras agotar intentos, `RETURN_ERROR` entrega `ToolResult(success=False)` al provider. `RAISE`
eleva:

- `ToolDeniedError` para permiso/aprobación;
- `ToolExecutionError` para tool desconocida, validación, timeout único u output inválido;
- `RetryExhaustedError` para una ejecución idempotente sin éxito tras todos los intentos.

El error público conserva código, tool name, attempts y timeout como detalles escalares seguros.
La excepción del callable sólo se encadena internamente cuando sea seguro y nunca se serializa.

## Binding de modelos y perfiles

`RuntimeModel` añade:

```python
def with_tools(
    self,
    registry: ToolRegistry,
    *,
    executor: ToolExecutor | None = None,
) -> RuntimeModel[Any]: ...
```

Si no se entrega executor se construye uno con el snapshot y políticas default, cuya lista de
permisos queda vacía; por lo tanto ninguna tool se ejecuta hasta que el host configure permisos.
Un executor explícito debe estar asociado al mismo snapshot lógico; mismatch de nombres/schemas
falla al bind.

`brain`, `structured`, `session` built-in y perfiles con `host_tools=disabled` rechazan el binding.
`controlled_agent` y custom profiles con host tools `controlled` o `explicit` pueden enlazarlo.
`native` no convierte provider-defined tools en host tools.

La vista tool-enabled no admite `with_structured_output()` en Phase 5: combinar structured output
terminal con un loop dynamic-tool requiere una decisión posterior. Ambos métodos fallan de forma
explícita cuando se intenta componerlos.

## Sesiones persistentes e híbridas

`Runtime.session()` y `resume_session()` agregan keyword-only `registry` y `executor` opcionales.
Sólo perfiles custom persistentes/híbridos con host tools habilitadas los aceptan.

Para crear una sesión tool-enabled, el adapter envía el snapshot en `thread/start.dynamicTools`.
Para reanudarla, el caller debe volver a proporcionar registry/executor; el runtime envía siempre
el snapshot actual y reemplaza cualquier lista restaurada por Codex. Si el descriptor indica un
perfil tool-enabled y falta el binding, se eleva `CapabilityError` antes de `thread/resume`.

Una sesión que no usa host tools envía lista vacía cuando el protocolo experimental está activo,
evitando que metadata antigua reactive tools. Descriptors no contienen definitions, schemas,
permisos ni indicadores capaces de expandir autoridad.

## Capabilities y seguridad efectiva

`CodexRuntime(experimental_dynamic_tools=False)` mantiene el comportamiento actual. Startup
consulta/valida soporte experimental sin habilitar tools. `runtime.capabilities().host_tools`
representa soporte upstream real; puede ser true aunque el flag esté apagado.

`model.effective_capabilities().host_tools` sólo es true cuando coinciden:

```text
provider capability
AND feature flag
AND profile permits host tools
AND security policy controlled/explicit
AND non-empty registry snapshot
AND compatible executor
```

El adapter conserva `approval_mode=deny_all`, sandbox read-only y workspace temporal vacío. No
habilita shell, filesystem write, network, browser, MCP, computer use ni tools nativas. El único
camino de efecto es el callable seleccionado por el executor host.

## Eventos y observabilidad

Se añaden:

```text
TOOL_APPROVAL_REQUESTED
TOOL_APPROVAL_RESOLVED
TOOL_DENIED
TOOL_FAILED
TOOL_RETRY_SCHEDULED
```

Flujo exitoso: requested → approval opcional → started → completed. Flujo denegado termina en
denied; fallo sin retry termina en failed; cada intento posterior lleva retry_scheduled → started.

Metadata canónica incluye `tool_name`, hash/ID de call, permission, side_effect, attempt,
max_attempts, duration_ms, success, denied, timed_out y error code. Arguments, output y contenido
de aprobación viven sólo en payload. No se exporta el callable ni `repr()` arbitrario.

LangSmith crea/finaliza un child run por call ID y representa aprobación/retry como eventos o
children acotados. OpenTelemetry usa span `proteo.tool`, span events para aprobación/retry y las
métricas existentes; no agrega invocation/call/session IDs como metric labels. Ambos respetan el
mismo payload projection y redactor de Phase 4.

## Adapter Codex experimental

El módulo provider-specific encapsula:

1. capability opt-in `capabilities.experimentalApi` durante initialize;
2. serialización de cada definition como function `DynamicToolSpec`;
3. inyección de `dynamicTools` al `thread/start`/`thread/resume` privado;
4. registro temporal de un handler para server request `item/tool/call`;
5. normalización a `ToolRequest` y dispatch al executor;
6. respuesta con content items de texto JSON y success/failure compatible;
7. reconciliación con `dynamicToolCall` de `item/started` y `item/completed`.

El handler se registra antes de iniciar el thread y se elimina en todos los terminales. Requests
con thread/turn/item desconocido se deniegan y nunca se enrutan a otro executor. Una cancelación
resuelve o cancela requests pendientes antes de cerrar el turno.

El shim usa request/response models generados cuando existan; cualquier acceso al cliente privado
queda en `_compat`/`experimental`. Startup verifica versión, fields, message-router hook y método.
Una incompatibilidad produce `CapabilityError` antes de account/model/inference tool-enabled. No
existe fallback de texto ni una segunda API de transporte pública.

## Packaging y compatibilidad

No se agregan dependencias. Los módulos neutrales se incluyen en wheel/sdist base. Los imports de
Codex experimental permanecen lazy y provider-specific. La versión pasa a `0.6.0` sólo en el
workstream de release, después de los contratos y tests.

La fase añade `docs/adr/0003-host-managed-tools.md` durante implementación para fijar autoridad
host, failure policy, idempotencia no durable y límite experimental. No cambia configuración JSON
v1 ni descriptors `prt1.*`.
