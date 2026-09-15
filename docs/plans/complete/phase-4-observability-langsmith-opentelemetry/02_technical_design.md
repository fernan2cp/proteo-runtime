# Technical Design — Phase 4

## Límite arquitectónico

La dependencia conserva esta dirección:

```text
core/runtime/provider ──> proteo_runtime.observability (contratos neutrales)
                                     │
                                     ├──> langsmith adapter ──> langsmith SDK
                                     └──> opentelemetry adapter ──> OTel API

Codex provider ──> Codex-native OTel launch configuration
```

`proteo_runtime.observability` no importa Codex, LangGraph, LangSmith u OpenTelemetry. Los módulos
opcionales viven bajo ese namespace pero sus imports externos son perezosos y nunca se ejecutan al
importar `proteo_runtime` o el namespace neutral.

## API pública neutral

La fase introducirá, sin exportarlos automáticamente desde el paquete raíz:

```python
class PayloadMode(StrEnum):
    METADATA_ONLY = "metadata_only"
    REDACTED = "redacted"
    FULL = "full"
    DISABLED = "disabled"


class ObservabilityStatus(StrEnum):
    DISABLED = "disabled"
    HEALTHY = "healthy"
    DEGRADED = "degraded"


class RuntimeObserver(Protocol):
    async def on_event(self, event: RuntimeEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ObserverBinding:
    observer: RuntimeObserver
    payload_mode: PayloadMode = PayloadMode.METADATA_ONLY


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    observers: tuple[ObserverBinding, ...] = ()
    strict: bool = False
    dispatch_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 10.0
```

`RuntimeEventBus` recibirá `ObservabilityConfig`, expondrá `emit()`, `flush()`, `close()` y
`status`, y mantendrá diagnostics sanitizados. Config vacía significa `disabled`. Dos bindings del
mismo objeto observer serán inválidos para evitar doble dispatch accidental.

`CodexRuntime.__init__()` aceptará `observability: ObservabilityConfig | None = None` y
`codex_native_otel: CodexNativeOtelConfig | None = None`. El runtime y los modelos/sesiones creados
por él compartirán una sola instancia de bus. `FakeRuntime` aceptará la misma configuración para
mantener contratos verificables sin SDKs externos.

`RuntimeResult` añadirá `observability_status: ObservabilityStatus`, default `disabled`, y seguirá
usando `diagnostics` para detalle seguro. `Runtime` añadirá
`observability_status() -> ObservabilityStatus`; las implementaciones y fakes se actualizarán en el
mismo cambio para conservar el protocolo runtime-checkable.

## Modelo de evento y payload

`RuntimeEvent` conservará sus campos existentes y añadirá un `payload` inmutable separado de
`metadata`. Metadata contiene únicamente atributos operativos JSON-safe. Payload contiene datos
que un modo distinto de `metadata_only` podría proyectar: input/output neutral, schema o datos de
tools. Raw provider nunca se promueve automáticamente desde `RuntimeResult.raw`.

Claves metadata canónicas:

```text
runtime.provider              runtime.version
profile                       security_policy
context_policy                model
reasoning_effort              ephemeral
structured_output             duration_ms
input_tokens                  cached_input_tokens
output_tokens                 reasoning_tokens
total_tokens                  retry_count
tool_call_count               error.type
error.code                    langgraph.run_id
```

Los IDs se exportan como atributos separados:

```text
proteo.invocation_id
proteo.session_id
proteo.turn_id
```

`proteo.session_id` usa el namespace `proteo.session:` seguido de
`sha256("proteo-observability-v1\0" + descriptor).hexdigest()`. El descriptor no aparece en
metadata, payload, diagnostics, span attributes, LangSmith thread IDs ni mensajes de error.
Eventos sin descriptor mantienen el atributo ausente, no una cadena vacía.

Cada invocación emite una secuencia monotónica. Lifecycle sin invocation usa la secuencia del
runtime. El bus usa un lock async por invocation ID y un lock separado de lifecycle; distintos
invocations pueden avanzar concurrentemente. Cada evento se entrega una vez a cada binding activo
en orden de registro.

## Proyección de payload y redacción

Antes de llamar a un exporter oficial se crea una copia proyectada:

- `disabled`: el binding no recibe eventos ni participa en health.
- `metadata_only`: `payload={}` y `result=None`; conserva status y usage sólo como escalares
  metadata.
- `redacted`: conserva nombres, tipos, tamaños y estructura; todos los valores de contenido se
  sustituyen por marcadores estables como `[REDACTED]`.
- `full`: conserva contenido neutral literal, nunca objetos SDK ni `raw`; aplica siempre redacción
  de secretos.

La redacción obligatoria elimina claves secret-shaped en cualquier profundidad, bearer tokens,
asignaciones credential-shaped, exception causes, headers, variables de entorno sensibles y
descriptors. No ejecuta `repr()` arbitrario sobre objetos desconocidos. Valores no JSON-safe se
convierten a un marcador de tipo seguro. Toda proyección crea copias y deja intacto el evento.

## Dispatch, degradación y strict mode

Para cada evento el bus intenta todos los observers activos. En modo default captura fallos por
binding, sanitiza exporter/type sin incluir payload o cause, añade un único diagnostic por
observer+invocation y marca `degraded`. Los observers posteriores aún reciben el evento.

Antes de entregar el terminal al caller, el runtime copia `RuntimeResult` con status/diagnostics
actualizados y coloca esa copia en el único `INVOCATION_COMPLETED`. `ainvoke()` y `astream()` ven el
mismo terminal enriquecido. Fallos de lifecycle quedan en el estado del runtime y se adjuntan a la
siguiente invocación si siguen vigentes.

En strict mode se intenta el fan-out completo y el cleanup aplicable; después se eleva
`ObservabilityError`. Una cancelación activa conserva `asyncio.CancelledError` y registra el fallo
de observabilidad sin sustituirla. Timeout de observer se trata como fallo de exporter. `close()` es
idempotente, llama `flush()` antes de `close()` y sólo cierra recursos que el observer declara como
propios.

## Integración con los flujos existentes

- `start()`/`close()` awaitarán lifecycle dispatch.
- Model/session `ainvoke()` continuará drenando el mismo stream interno instrumentado; no habrá
  un segundo camino de eventos.
- `astream()` despachará cada evento antes de yield; abandonar/cancelar el iterator conserva el
  cleanup existente y emite el terminal disponible sin inventar success.
- Structured output conserva una invocation raíz; cada intento, validation failure y retry queda
  anidado mediante attempt/retry metadata y no crea resultados exitosos duplicados.
- `RuntimeNode` no invoca exporters. Sólo propaga `langgraph_run_id`/tags seguros y consume el
  stream instrumentado, por lo que no duplica spans.
- Session create/resume/close/archive/delete/migrate usa el bus compartido. El descriptor sólo se
  transforma dentro de la proyección de correlación.

## LangSmithObserver

Se publicará desde `proteo_runtime.observability.langsmith`. Su constructor recibe un cliente
inyectado opcional, project name, tags base y ownership del cliente. Sin cliente, crea el cliente
SDK usando su configuración estándar; Proteo nunca lee ni devuelve la API key.

El adapter mantiene una tabla efímera de runs abiertos por invocation/turn/tool ID:

```text
LangGraph run (si fue propagado)
└── proteo.runtime
    └── proteo.turn
        ├── proteo.retry
        ├── proteo.validation
        └── proteo.tool:<name>
```

Los start events crean runs; completed/failed/interrupted/cancelled los finalizan exactamente una
vez. Eventos puntuales sin intervalo se representan como child run cerrado. Parent LangGraph se
usa sólo si `langgraph.run_id` es UUID válido; de lo contrario se crea raíz Proteo y se registra
diagnostic local no sensible. `metadata_only` envía inputs/outputs vacíos y metadata canónica. El
SDK conserva su batching; cualquier método síncrono potencialmente bloqueante se ejecuta fuera del
event loop.

## OpenTelemetryObserver

Se publicará desde `proteo_runtime.observability.opentelemetry`. Recibe tracer/meter o providers
inyectados; si no se suministran usa las APIs globales sin reemplazarlas. Sólo cierra providers o
processors creados y marcados explícitamente como owned por el caller.

Spans:

```text
proteo.runtime
proteo.invocation
proteo.turn
proteo.retry
proteo.validation
proteo.tool
```

Los atributos usan las claves canónicas y valores escalares/arrays permitidos por OTel. Fallos
marcan status error y registran únicamente tipo/código neutral, no mensajes provider ni causes.
Retries/validation también se añaden como span events al parent para consulta agregada.

Métricas mínimas:

```text
proteo.runtime.invocations          counter
proteo.runtime.errors               counter
proteo.runtime.duration             histogram (ms)
proteo.runtime.tokens               counter por token.type
proteo.runtime.retries              counter
proteo.runtime.tool_calls           counter
proteo.observability.failures       counter por observer.type
```

No se usan invocation/session/turn IDs como labels de métricas para evitar cardinalidad alta; esos
IDs sólo viven en spans/runs. Ninguna métrica se emite cuando el valor fuente es desconocido.

## Correlación entre exporters

Ambos adapters copian literalmente los IDs Proteo derivados del mismo evento. LangSmith usa esos
valores como metadata/thread correlation y OTel como span attributes. Se permite que cada backend
genere sus propios run/span/trace IDs. No se enlazan exporters mediante SDKs entre sí y no se
promete un `trace_id` común.

## Codex-native OpenTelemetry

`CodexNativeOtelConfig` vivirá bajo `proteo_runtime.providers.codex` y contendrá sólo opciones no
secretas: `enabled`, `environment`, tipos de exporter y endpoints/TLS paths. Headers estáticos,
tokens y API keys no forman parte del objeto Proteo; el host debe suministrarlos por el mecanismo
seguro soportado por su deployment, fuera de model config y diagnostics.

Con `enabled=False` no se envía override alguno. Con opt-in, startup valida que la versión SDK/bin
y su configuración soportan las claves solicitadas, fuerza `otel.log_user_prompt=false`, y aplica
overrides antes de iniciar app-server. Si no puede garantizarlo, falla con `CapabilityError` o
`ConfigurationError` antes de account/model access.

Proteo sólo añade `proteo.invocation_id`, `proteo.session_id` y `proteo.turn_id` cuando upstream
ofrezca propagación explícita. Si no existe esa capability, la telemetría nativa puede habilitarse
sin esos campos y expone `correlation_supported=False`; nunca simula correlación ni reescribe
telemetría del provider. Habilitarla no modifica prompts, modelo, effort, sandbox, approvals,
timeouts, resultados o lifecycle de sesiones.

## Packaging y compatibilidad

Extras:

```toml
langsmith = ["langsmith>=0.12,<0.13"]
otel = ["opentelemetry-api>=1.44,<2"]
all = ["langgraph>=1.2,<2", "langsmith>=0.12,<0.13", "opentelemetry-api>=1.44,<2"]
```

`dev` añade `opentelemetry-sdk>=1.44,<2` para exporters/readers in-memory. Imports sin extra deben
fallar al construir/configurar el adapter con guía de instalación; importar core, Codex o el
namespace neutral sigue funcionando. La fase no migra datos, descriptors, config JSON ni history.
