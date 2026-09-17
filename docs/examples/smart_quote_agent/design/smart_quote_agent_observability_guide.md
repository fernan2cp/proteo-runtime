# Smart Quote Agent — Observability & Telemetry Implementation Guide

**Project:** Proteo Runtime
**Example:** Smart Quote Agent
**Recommended location:** `examples/smart_quote_agent/`
**Implementation phase:** Phase 2 of the example, after the functional agent is complete and stable
**Baseline:** Proteo Runtime `0.6.x`, with Phases 0–5 completed
**Primary goal:** make the agent's runtime behavior inspectable locally while demonstrating the existing Proteo observability architecture, LangSmith mapping, and OpenTelemetry mapping without introducing external infrastructure as a requirement.

---

## 1. Purpose

This document defines the second implementation phase of the Smart Quote Agent example.

Phase 1 builds the working agent:

```text
LangGraph
+ Codex
+ structured routing/planning
+ host-managed tools
+ login/logout HITL
+ staff/client authorization
+ quote persistence in SQLite
```

Phase 2 adds observability:

```text
Proteo RuntimeEvent stream
+ local SQLite event recorder
+ LangSmith projection recorder
+ OpenTelemetry projection recorder
+ external inspection CLI
```

The observability phase must not change business behavior.

The agent must work identically with observability:

```text
disabled
local only
local + real LangSmith
local + real OpenTelemetry
```

Observability remains an inspection concern, not execution authority.

---

## 2. Architectural principle

Do **not** implement SQLite as a replacement backend for LangSmith or OpenTelemetry.

Instead, use the existing provider-neutral Proteo event bus as the source:

```text
                       Proteo Runtime
                             |
                       RuntimeEventBus
                             |
        +--------------------+--------------------+
        |                    |                    |
        v                    v                    v
SQLiteEventObserver   LangSmithObserver   OpenTelemetryObserver
        |                    |                    |
        v                    v                    v
runtime_events      Recording client      Recording tracer/meter
        |                    |                    |
        +--------------------+--------------------+
                             |
                             v
                  observability.sqlite3
                             |
                             v
                 inspect_observability.py
```

The demo must show three different representations of the same execution:

```text
1. Neutral Proteo runtime events
2. LangSmith run hierarchy
3. OpenTelemetry spans and metrics
```

All three should be correlatable through neutral Proteo identifiers.

---

## 3. Existing Proteo contracts to reuse

Use the public observability contracts already implemented by Proteo Runtime.

Conceptually:

```python
from proteo_runtime.observability import (
    ObservabilityConfig,
    ObserverBinding,
    PayloadMode,
    RuntimeObserver,
)
```

The example should also use the official observers:

```python
from proteo_runtime.observability.langsmith import LangSmithObserver
from proteo_runtime.observability.opentelemetry import OpenTelemetryObserver
```

The local demo layer must adapt to these existing contracts rather than reimplementing their mapping logic.

---

## 4. Important behavior already provided by Proteo

The Phase 4 event bus already provides:

- ordered asynchronous observer dispatch;
- per-observer `PayloadMode`;
- metadata projection;
- secret filtering;
- observer failure isolation by default;
- optional strict observability mode;
- correlation metadata;
- observer flush/close lifecycle;
- observability degraded diagnostics.

The demo should take advantage of this behavior instead of duplicating it.

Recommended observer mode for all local recorders:

```text
PayloadMode.METADATA_ONLY
```

This makes the SQLite telemetry intentionally content-safe.

Do not persist:

```text
prompts
responses
passwords
tool arguments
tool results
raw provider payloads
credentials
session descriptors
exception objects
```

---

## 5. Storage layout

Keep business and telemetry data separate.

```text
examples/
└── smart_quote_agent/
    └── data/
        ├── demo.sqlite3
        └── observability.sqlite3
```

### `demo.sqlite3`

Owned by the business demo.

Contains:

```text
users
customers
products
quotes
quote_lines
```

### `observability.sqlite3`

Owned by the telemetry demo.

Contains:

```text
runtime_events
langsmith_runs
otel_spans
otel_span_events
otel_metrics
```

Do not create foreign-key relationships between the two databases.

Correlation must happen through IDs, not database coupling.

---

## 6. Initialization strategy

The Phase 1 initializer should remain responsible for business data.

Recommended:

```bash
python examples/smart_quote_agent/init_demo.py --reset
```

The observability phase may extend the initializer or add a separate helper.

Preferred option:

```bash
python examples/smart_quote_agent/init_observability.py --reset
```

This separation makes the two implementation phases explicit.

Alternative:

```bash
python init_demo.py --reset --with-observability
```

is acceptable, but a dedicated telemetry initializer is clearer for the showcase.

### Recommended Phase 2 command

```bash
python examples/smart_quote_agent/init_observability.py --reset
```

Behavior:

1. create `data/`;
2. remove `observability.sqlite3` only with explicit `--reset`;
3. create telemetry schema;
4. print DB path;
5. exit without starting Codex.

---

## 7. `runtime_events` table

This table records the provider-neutral event stream delivered to a metadata-only observer.

Recommended schema:

```sql
CREATE TABLE runtime_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at       TEXT NOT NULL,
    occurred_at       TEXT NOT NULL,
    event_id          TEXT NOT NULL,
    event_kind        TEXT NOT NULL,
    invocation_id     TEXT NULL,
    session_id        TEXT NULL,
    turn_id           TEXT NULL,
    runtime_name      TEXT NULL,
    model             TEXT NULL,
    profile           TEXT NULL,
    reasoning_effort  TEXT NULL,
    tool_name         TEXT NULL,
    tool_call_id      TEXT NULL,
    status            TEXT NULL,
    duration_ms       REAL NULL,
    metadata_json     TEXT NOT NULL
);
```

Recommended indexes:

```sql
CREATE INDEX idx_runtime_events_invocation
    ON runtime_events(invocation_id);

CREATE INDEX idx_runtime_events_kind
    ON runtime_events(event_kind);

CREATE INDEX idx_runtime_events_occurred_at
    ON runtime_events(occurred_at);
```

### Storage rules

`metadata_json` stores only the already-projected metadata received from the event bus.

Do not reconstruct or enrich it using application secrets.

`recorded_at` is local recorder time.

`occurred_at` is event time.

Both should be stored as UTC ISO-8601.

---

## 8. `SQLiteEventObserver`

Create a small application-owned observer:

```python
class SQLiteEventObserver:
    async def on_event(self, event: RuntimeEvent) -> None:
        ...

    async def flush(self) -> None:
        ...

    async def close(self) -> None:
        ...
```

Responsibilities:

- accept only projected `RuntimeEvent` values;
- serialize safe metadata to JSON;
- insert one row per event;
- never inspect application password state;
- never fetch additional payload from the runtime;
- keep lifecycle methods idempotent.

Recommended implementation location:

```text
examples/smart_quote_agent/observability.py
```

The observer must not become part of `proteo_runtime`.

It is a demo adapter.

---

## 9. Runtime event fields to surface

Extract useful scalar fields from metadata when present:

```text
proteo.runtime
proteo.invocation_id
proteo.session_id
proteo.turn_id
proteo.model
proteo.profile
proteo.reasoning_effort
proteo.latency_ms
tool_name
tool_call_id
status
attempt
max_attempts
success
denied
timed_out
error_code
input_tokens
cached_input_tokens
output_tokens
reasoning_tokens
total_tokens
tool_call_count
```

Keep the complete safe metadata object in `metadata_json`.

Do not fail the observer if a field is absent.

Observability is schema-tolerant at the local inspection layer.

---

## 10. LangSmith strategy

The demo must use the **real Proteo `LangSmithObserver` mapping**.

Do not create a custom mapping that imitates LangSmith.

Instead, inject an application-owned recording client:

```python
recording_client = RecordingLangSmithClient(db)

observer = LangSmithObserver(
    client=recording_client,
    project_name="proteo-smart-quote-demo",
    owns_client=False,
)
```

The existing observer remains responsible for converting neutral events into:

```text
proteo.runtime
proteo.turn
proteo.retry
proteo.validation
proteo.tool
```

The recording client only captures the calls the observer makes.

---

## 11. `RecordingLangSmithClient`

Implement the minimal methods needed by the current observer:

```python
create_run(...)
update_run(...)
flush()      # optional
close()      # optional
```

It should behave like a very small local stand-in for the LangSmith SDK client.

It must not reproduce LangSmith internals.

### `langsmith_runs` table

Recommended schema:

```sql
CREATE TABLE langsmith_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL UNIQUE,
    parent_run_id   TEXT NULL,
    name            TEXT NOT NULL,
    run_type        TEXT NULL,
    project_name    TEXT NULL,
    started_at      TEXT NULL,
    ended_at        TEXT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    error           TEXT NULL,
    tags_json       TEXT NOT NULL DEFAULT '[]',
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);
```

Indexes:

```sql
CREATE INDEX idx_langsmith_runs_parent
    ON langsmith_runs(parent_run_id);

CREATE INDEX idx_langsmith_runs_started
    ON langsmith_runs(started_at);
```

### `create_run`

On `create_run(...)`:

- determine or generate a stable local `run_id`;
- store parent relation;
- store name;
- store run type;
- store project name;
- store start time;
- store metadata;
- ignore content fields that are absent under metadata-only mode;
- return an object or mapping exposing `id` or `run_id`, so the existing
  `LangSmithObserver` can reuse that identifier for parent/child relationships.

Minimal example:

```python
return {"id": run_id}
```

### `update_run`

On `update_run(...)`:

- update end time;
- update status;
- persist safe error string if present.

Do not store prompt/response bodies.

---

## 12. Optional real LangSmith mode

The local recording mode must be the default.

Optional real export may be enabled explicitly.

Recommended configuration:

```text
DEMO_LANGSMITH=local
DEMO_LANGSMITH=real
DEMO_LANGSMITH=off
```

Default:

```text
local
```

### `real`

Use the official `LangSmithObserver` without injecting the recording client.

Credentials remain managed by the normal LangSmith SDK/environment.

The example README must not include real API keys.

### `local + real`

If desired, bind two separate `LangSmithObserver` instances:

```text
local recording observer
real LangSmith observer
```

This is optional and should not be required for the base implementation.

---

## 13. OpenTelemetry strategy

Use the real Proteo `OpenTelemetryObserver`.

Do not write spans manually from `RuntimeEvent`.

Inject local tracer and meter implementations or OpenTelemetry SDK-backed local exporters.

### Recommended balance

For this demo, prefer:

```text
real OpenTelemetry SDK
+
small SQLite span exporter
+
small SQLite metric exporter
```

over implementing a fake tracer API from scratch.

This demonstrates that Proteo's observer works with normal OpenTelemetry concepts while still keeping the demo self-contained.

If keeping dependencies minimal is more important, a small recording tracer/meter compatible with the observer is acceptable, but SDK-backed recording is the preferred showcase.

---

## 14. Required OpenTelemetry dependency

The current base `otel` extra provides the API layer.

For the local demo exporter, use the SDK in the example environment:

```text
opentelemetry-sdk
```

Do not make it a new mandatory dependency of the Proteo base package.

The example README should instruct:

```bash
uv sync --extra dev --extra langgraph --extra otel
```

or equivalent.

If the example is intended to work from an installed package rather than contributor environment, document the additional SDK package explicitly.

---

## 15. `otel_spans` table

Recommended schema:

```sql
CREATE TABLE otel_spans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id          TEXT NOT NULL,
    span_id           TEXT NOT NULL UNIQUE,
    parent_span_id    TEXT NULL,
    name              TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT NULL,
    duration_ms       REAL NULL,
    status_code       TEXT NULL,
    status_message    TEXT NULL,
    attributes_json   TEXT NOT NULL DEFAULT '{}'
);
```

Indexes:

```sql
CREATE INDEX idx_otel_spans_trace
    ON otel_spans(trace_id);

CREATE INDEX idx_otel_spans_parent
    ON otel_spans(parent_span_id);

CREATE INDEX idx_otel_spans_started
    ON otel_spans(started_at);
```

---

## 16. `otel_span_events` table

Recommended:

```sql
CREATE TABLE otel_span_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    span_id          TEXT NOT NULL,
    name             TEXT NOT NULL,
    occurred_at      TEXT NOT NULL,
    attributes_json  TEXT NOT NULL DEFAULT '{}'
);
```

This is useful for events such as:

```text
retry
validation failure
tool approval
exception
```

The inspector can display them nested under the span.

---

## 17. `otel_metrics` table

Recommended schema:

```sql
CREATE TABLE otel_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at      TEXT NOT NULL,
    instrument_name  TEXT NOT NULL,
    instrument_type  TEXT NOT NULL,
    value            REAL NOT NULL,
    attributes_json  TEXT NOT NULL DEFAULT '{}'
);
```

Expected Proteo metrics include concepts such as:

```text
proteo.runtime.events
proteo.runtime.invocations
proteo.runtime.errors
proteo.runtime.tokens
proteo.runtime.retries
proteo.runtime.tool_calls
proteo.runtime.duration
proteo.observability.failures
```

Do not add high-cardinality IDs as metric labels.

Invocation/session/turn correlation belongs primarily in spans/events.

---

## 18. OpenTelemetry exporter implementation

Recommended application-owned classes:

```python
class SQLiteSpanExporter(...):
    ...

class SQLiteMetricExporter(...):
    ...
```

They write completed telemetry records to `observability.sqlite3`.

The Proteo observer is still responsible for deciding:

```text
which RuntimeEvent starts a span
which RuntimeEvent ends a span
which metadata becomes attributes
which events increment metrics
```

The SQLite exporter only persists the resulting OTel data.

---

## 19. Correlation strategy

The inspection DB should make it easy to correlate:

```text
RuntimeEvent
LangSmith run
OpenTelemetry span
```

The canonical correlation values are the neutral Proteo identifiers where available:

```text
proteo.invocation_id
proteo.session_id
proteo.turn_id
```

Store these values inside safe metadata/attributes.

Do not require a shared OpenTelemetry `trace_id` between Proteo and provider-native telemetry.

Do not invent that guarantee.

---

## 20. Codex-native OpenTelemetry

Do **not** make Codex-native OpenTelemetry part of the mandatory demo path.

The base observability demo should show:

```text
Proteo RuntimeEvent
    -> LangSmithObserver
    -> OpenTelemetryObserver
```

Codex-native OTel may be documented as an optional advanced mode:

```text
DEMO_CODEX_NATIVE_OTEL=1
```

only if the installed Codex runtime supports it.

It must remain:

```text
optional
disabled by default
provider-specific
not required for demo success
```

The local SQLite inspector does not need to merge provider-native spans into the neutral trace.

---

## 21. Configuration factory

Create one helper:

```python
def create_observability_config(...) -> ObservabilityConfig:
    ...
```

Recommended default bindings:

```text
SQLiteEventObserver
LangSmithObserver(RecordingLangSmithClient)
OpenTelemetryObserver(local tracer/meter)
```

All with:

```text
PayloadMode.METADATA_ONLY
```

Conceptual example:

```python
config = ObservabilityConfig(
    observers=(
        ObserverBinding(
            SQLiteEventObserver(...),
            PayloadMode.METADATA_ONLY,
        ),
        ObserverBinding(
            LangSmithObserver(
                client=RecordingLangSmithClient(...),
                project_name="proteo-smart-quote-demo",
                owns_client=False,
            ),
            PayloadMode.METADATA_ONLY,
        ),
        ObserverBinding(
            OpenTelemetryObserver(
                tracer=tracer,
                meter=meter,
            ),
            PayloadMode.METADATA_ONLY,
        ),
    ),
    strict=False,
)
```

The application then passes this config to `CodexRuntime`.

### Application-created `ToolExecutor` event wiring

`CodexRuntime` automatically sends runtime/turn events through its configured
observability bus. Application-created `ToolExecutor` instances are different:
their tool lifecycle events are exported only when their public `event_sink`
hook is connected.

Phase 2 must therefore wire executors created by the Smart Quote Agent to the
same application observability pipeline used by the demo.

Relevant events include:

```text
tool_requested
validation_failed
tool_approval_requested
tool_approval_resolved
tool_started
tool_retry_scheduled
tool_completed
tool_denied
tool_failed
```

Do **not** call the private `CodexRuntime._dispatch` method from the example.
Use only public observability/tool contracts and keep observer lifecycle
ownership explicit so the same observer is not closed twice.

This wiring is required especially for the dedicated host-side `create_quote`
executor, whose lifecycle is not automatically part of a Codex model turn.

---

## 22. Failure behavior

Keep:

```text
strict=False
```

for the demo.

If the SQLite observer, recording LangSmith client, or local OTel exporter fails:

```text
agent inference should continue
observability should become degraded
diagnostics should record the failure
```

This is an important feature to demonstrate.

Optional inspector output:

```text
Observability status: degraded
Failure:
  observer: SQLiteEventObserver
  code: observability.dispatch_failed
```

Do not crash quote creation because the telemetry DB is unavailable in normal demo mode.

---

## 23. `inspect_observability.py`

This script must be independent from the agent.

It reads only:

```text
observability.sqlite3
```

It never imports or starts Codex.

Recommended commands:

```bash
python inspect_observability.py
python inspect_observability.py --last
python inspect_observability.py --limit 5
python inspect_observability.py --invocation <id>
python inspect_observability.py --events
python inspect_observability.py --langsmith
python inspect_observability.py --otel
```

Keep the parser small with `argparse`.

---

## 24. Default inspector view

Running:

```bash
python inspect_observability.py
```

should show recent invocations.

Recommended output:

```text
Recent Proteo invocations
────────────────────────────────────────────────────────────

#  Invocation        Started     Duration   Tools   Status
1  inv_8ca1...       12:41:02    4.21 s        3    completed
2  inv_4fed...       12:39:15    1.82 s        1    completed
3  inv_93ab...       12:37:08    3.02 s        2    completed
```

The summary should be derived from local `runtime_events`.

Do not require LangSmith/OTel tables to exist for this view.

`--last` means the most recent **Proteo runtime invocation**, not necessarily
the most recent CLI message. Host-only interactions such as deterministic
help, scope rejection, acknowledgement, login/logout, authorization guards,
discount HITL, or direct DB resolution may produce no runtime invocation at all.

One user interaction may therefore produce zero, one, or multiple Proteo
runtime invocations.

---

## 25. `--last` detailed view

Recommended format:

```text
Invocation inv_8ca1...
Started: 2026-09-16T12:41:02+00:00
Status: completed
Model: ...
Profile: controlled_agent
Reasoning: low
Duration: 4210 ms


Runtime Events
────────────────────────────────────────
12:41:02  invocation_started
12:41:02  turn_started
12:41:03  tool_requested          list_products
12:41:03  tool_started            list_products
12:41:03  tool_completed          list_products
12:41:04  turn_completed
12:41:04  invocation_completed
```

This example represents a controlled-agent catalog request.

Persistent quote creation has a different shape:

```text
Structured planner invocation
────────────────────────────────────────
invocation_started
turn_started
turn_completed
invocation_completed

Host-side deterministic work
────────────────────────────────────────
customer resolution      [no RuntimeEvent]
product resolution       [no RuntimeEvent]
discount HITL            [no RuntimeEvent]

Direct create_quote ToolExecutor
────────────────────────────────────────
tool_requested
tool_approval_requested
tool_approval_resolved
tool_started
tool_completed
```

The direct `create_quote` tool events are visible only when the application
has connected that executor's `event_sink` to the observability pipeline.

Then show the corresponding projections for the selected invocation/event group.

---

## 26. LangSmith projection output

Example:

```text
LangSmith Projection
────────────────────────────────────────

proteo.runtime
└── proteo.turn
    └── proteo.tool [list_products]
```

For host-side `create_quote`, the local recording may instead contain a
standalone tool run/event group associated with its own invocation identifier,
depending on how the application wires the direct `ToolExecutor`.

Build the tree from:

```text
run_id
parent_run_id
```

Do not infer business meaning from names beyond what the observer recorded.

---

## 27. OpenTelemetry projection output

Example:

```text
OpenTelemetry Spans
────────────────────────────────────────

proteo.invocation        4210 ms
proteo.turn              4178 ms
proteo.tool                12 ms
```

Group and order spans primarily by safe Proteo correlation attributes such as
`proteo.invocation_id` and timestamps.

Display a parent/child tree only when the exported OpenTelemetry span context
actually contains that relationship. Do not fabricate hierarchy from timing or
span names alone.

When span events exist:

```text
proteo.tool
  event: tool_approval_requested
  event: tool_approval_resolved
```

Metrics are low-cardinality and should be presented as recent/aggregate
telemetry, not as exact per-invocation values:

```text
OpenTelemetry Metrics — recent/aggregate
────────────────────────────────────────

proteo.runtime.events          ...
proteo.runtime.invocations     ...
proteo.runtime.tool_calls      ...
proteo.runtime.errors          ...
proteo.runtime.tokens          ...
proteo.runtime.duration        ...
```

`--invocation` may filter RuntimeEvents, LangSmith runs, and OTel spans by
correlation identifiers. Do not claim exact invocation-level ownership for
metrics that intentionally omit high-cardinality invocation labels.

---

## 28. Inspector filtering

Support only small, useful filters.

Recommended:

```text
--last
--limit N
--invocation ID
--events
--langsmith
--otel
```

Optional:

```text
--kind tool_completed
```

Do not implement:

```text
interactive SQL shell
dashboard server
web UI
query language
live tail daemon
```

Those would expand the demo without demonstrating additional Proteo behavior.

---

## 29. Host-only observability boundary

Login/logout and other deterministic application behavior are host-owned.

Do not create synthetic Proteo runtime events merely to make every CLI turn
appear in telemetry.

Examples that may legitimately remain outside the Proteo runtime stream:

```text
help / capability response
out_of_scope rejection
acknowledgement
login / logout
scope and authorization guards
discount HITL
direct customer/product DB resolution
```

This is intentional: the observability database demonstrates Proteo runtime
behavior, not a full application audit log.

Do not create synthetic Proteo runtime events for credentials.

Allowed:

```text
console:
Logged in as Demo Staff
```

Not allowed in telemetry:

```text
password
raw username/password prompt
password success/failure details containing credential values
```

A generic host-side event table is unnecessary for this demo.

Keep the observability DB focused on Proteo runtime behavior.

---

## 30. Quote correlation

The business quote ID is not automatically a Proteo runtime ID.

If useful, the host may safely attach a low-risk metadata value after creation:

```text
demo.quote_id
```

but only if the existing invocation/event API supports host metadata cleanly.

Do not modify Proteo core only to add this to the demo.

It is acceptable for quote correlation to remain visible through:

```text
tool_name=create_quote
invocation_id
timestamp
```

The demo should not add architecture just to force business/runtime correlation.

---

## 31. Privacy and redaction tests

Add local demo tests for sensitive values.

Use canaries:

```text
DEMO_PASSWORD_CANARY
DEMO_API_KEY_CANARY
DEMO_SECRET_CANARY
```

Verify they do not appear in:

```text
runtime_events.metadata_json
langsmith_runs.metadata_json
otel_spans.attributes_json
otel_span_events.attributes_json
otel_metrics.attributes_json
```

Also verify actual demo password:

```text
1234
```

is never written into the observability DB.

Because `1234` may coincidentally appear in timestamps/IDs, use a unique test password canary in test fixtures rather than relying only on literal `1234`.

---

## 32. Observability database retention

The demo does not need retention policies.

`observability.sqlite3` grows until reset.

Reset command:

```bash
python init_observability.py --reset
```

This is sufficient.

No rotation, archival, pruning, or TTL is required.

---

## 33. Concurrency

SQLite access should be simple and safe for the demo.

Recommended:

- open short-lived SQLite connections per operation/thread;
- do not share one default `sqlite3.Connection` between the asyncio event loop
  and `LangSmithObserver` worker threads;
- enable WAL;
- configure a bounded `busy_timeout` (for example 5000 ms);
- keep transactions short;
- use normal SQLite transaction semantics;
- serialize local telemetry writes only if needed.

`LangSmithObserver.on_event()` may execute client calls in a worker thread, so
the recording client must use thread-safe connection ownership rather than one
shared default SQLite connection.

Do not build a background queue unless measurement shows it is necessary.

The event bus already dispatches observers asynchronously.

The recorder should remain small.

---

## 34. File layout after Phase 2

Recommended final structure:

```text
examples/
└── smart_quote_agent/
    ├── README.md
    ├── app.py
    ├── init_demo.py
    ├── init_observability.py
    ├── inspect_observability.py
    │
    ├── database.py
    ├── models.py
    ├── auth.py
    ├── tools.py
    ├── graph.py
    ├── hitl.py
    │
    ├── observability.py
    ├── telemetry_db.py
    ├── langsmith_recording.py
    ├── otel_recording.py
    │
    └── data/
        ├── .gitkeep
        ├── demo.sqlite3
        └── observability.sqlite3
```

Generated SQLite databases should normally be `.gitignore`d.

Commit only:

```text
data/.gitkeep
```

---

## 35. Responsibilities by file

### `observability.py`

- observer configuration factory;
- bind local/real observers;
- mode selection;
- no SQL details.

### `telemetry_db.py`

- SQLite connection;
- schema creation;
- shared insert/read helpers;
- UTC helpers.

### `langsmith_recording.py`

- `RecordingLangSmithClient`;
- persistence into `langsmith_runs`.

### `otel_recording.py`

- local OpenTelemetry SDK/exporter setup;
- SQLite span exporter;
- SQLite metric exporter.

### `init_observability.py`

- create/reset telemetry DB.

### `inspect_observability.py`

- read-only CLI;
- render recent invocation summaries;
- render event list;
- render LangSmith tree;
- render OTel span tree;
- render metric summary.

---

## 36. Configuration modes

Recommended environment option:

```text
DEMO_OBSERVABILITY=off
DEMO_OBSERVABILITY=local
DEMO_OBSERVABILITY=local+langsmith
```

Default:

```text
local
```

Meaning:

### `off`

No observer bindings.

### `local`

```text
SQLiteEventObserver
Recording LangSmith client
Local OpenTelemetry SQLite exporters
```

No external credentials.

### `local+langsmith`

Same local recording plus real LangSmith export.

Optional later:

```text
local+all
```

for real LangSmith + external OTel.

Do not make this necessary for Phase 2 completion.

---

## 37. Demo execution workflow

Recommended:

```bash
python init_demo.py --reset
python init_observability.py --reset
python app.py
```

In another terminal:

```bash
python inspect_observability.py
```

After creating a quote:

```bash
python inspect_observability.py --last
```

This lets the audience see:

```text
terminal 1:
what the agent did

terminal 2:
how Proteo observed it
```

That is the central educational effect of Phase 2.

---

## 38. Recommended live demonstration

Use this sequence:

```text
1. Start agent with local observability enabled.
2. Ask for products.
3. Inspect latest invocation.
4. Login as staff.
5. Create quote with discount.
6. Approve persistence.
7. Inspect the structured planner invocation and the direct `create_quote`
   ToolExecutor event group separately.
8. Show which quote-resolution/HITL steps were intentionally host-only.
9. Show RuntimeEvent sequence.
10. Show LangSmith projection.
11. Show OpenTelemetry spans grouped by safe correlation identifiers.
12. Show recent/aggregate OTel metrics.
13. Open SQLite or run query proving no password exists.
```

Optional:

```text
14. Re-run with real LangSmith enabled.
15. Compare local LangSmith projection with remote trace.
```

---

## 39. Acceptance criteria

### Local event capture

- every Proteo event delivered to the local observer is persisted;
- metadata-only mode is used;
- ordering by `occurred_at` is preserved;
- invocation correlation works;
- tool lifecycle events are visible.

### LangSmith projection

- official `LangSmithObserver` is used;
- no custom LangSmith mapping is implemented;
- recording client persists `create_run`/`update_run`;
- parent/child hierarchy is reconstructable;
- tool runs are visible.

### OpenTelemetry projection

- official `OpenTelemetryObserver` is used;
- spans are persisted;
- spans can be grouped by safe Proteo correlation identifiers;
- parent/child hierarchy is displayed only when present in exported span context;
- metrics are persisted as low-cardinality recent/aggregate telemetry;
- tool/retry/validation activity is visible when produced.

### Inspector

- lists recent Proteo invocations;
- clearly states that host-only CLI interactions may produce no invocation;
- can display last runtime invocation;
- can filter RuntimeEvents/LangSmith runs/OTel spans by invocation ID;
- can display raw neutral event sequence;
- can display LangSmith hierarchy;
- can display OTel spans and recent/aggregate metrics;
- starts no Codex process.

### Safety

- passwords never reach telemetry DB;
- no prompts/responses in metadata-only mode;
- no raw provider payload;
- no session descriptor;
- observer failure does not fail normal inference;
- external exporters remain optional.

### Architecture

- no business tables are added to observability DB;
- no observability tables are added to business DB;
- no Proteo core changes are required;
- application-created `ToolExecutor` instances use their public `event_sink`
  hook when their lifecycle must enter the observability pipeline;
- no private `CodexRuntime._dispatch` call is used from the example;
- local recorders remain under the example;
- real LangSmith/OpenTelemetry can be enabled without changing agent business logic.

---

## 40. Tests

Recommended demo tests:

```text
test_sqlite_event_observer.py
test_recording_langsmith_client.py
test_sqlite_otel_exporters.py
test_observability_redaction.py
test_inspector_queries.py
```

Use fakes for `RuntimeEvent`.

Do not consume Codex quota in default tests.

Recommended integration smoke:

```text
explicit opt-in
real Codex
one simple invocation
local telemetry DB
assert invocation + turn + terminal event exist
```

Real LangSmith should remain a separate optional smoke.

---

## 41. What this phase demonstrates

After implementation, the example should clearly demonstrate:

```text
Proteo emits one neutral runtime event model.

The same event stream can be consumed by:
- a local observer,
- LangSmith,
- OpenTelemetry.

The application does not depend on any exporter.

Observability is inspectable without cloud infrastructure.

Exporter failure is isolated from inference.

Correlation remains provider-neutral.

Sensitive application credentials stay outside runtime telemetry.
```

---

## 42. What this phase does not demonstrate

Do not claim that the local demo provides:

```text
production logging infrastructure
distributed tracing backend
long-term metrics storage
high-volume telemetry ingestion
real-time dashboards
SIEM integration
full LangSmith server compatibility
full OTLP collector behavior
provider-native trace unification
```

Those are outside the purpose of the example.

---

## 43. Implementation size boundary

Keep Phase 2 small.

Recommended target:

```text
SQLite event observer:          ~80–120 lines
LangSmith recording client:     ~80–120 lines
OTel exporters/setup:          ~120–180 lines
Telemetry DB helpers:           ~80–120 lines
Inspector:                     ~150–250 lines
Initializer/tests/docs:        as needed
```

Avoid expanding this into an observability product.

---

## 44. Frozen design decisions

```text
- Observability is implemented only after the agent works.
- Business and telemetry use separate SQLite databases.
- Proteo RuntimeEvent is the source of truth.
- SQLite does not replace LangSmith or OpenTelemetry.
- Official Proteo LangSmithObserver is reused.
- Official Proteo OpenTelemetryObserver is reused.
- Local LangSmith recording captures observer client calls.
- Local OpenTelemetry recording captures spans/metrics.
- PayloadMode.METADATA_ONLY is the default.
- Login credentials never enter telemetry.
- Host-only graph behavior does not require synthetic RuntimeEvents.
- Inspector is a separate read-only CLI.
- Local observability requires no cloud credentials.
- External LangSmith is optional.
- Codex-native OTel is optional and out of the base path.
- Observer failure does not fail agent execution by default.
- Direct application `ToolExecutor` events are wired through the public
  `event_sink` contract when observability is required.
- No changes to Proteo core are required for this phase.
```

---

## 45. Relationship with the Phase 1 guide

Implement in this order:

```text
Phase 1
Smart Quote Agent
    |
    | functional validation complete
    v
Phase 2
Observability & Telemetry
```

Do not mix Phase 2 requirements into the first implementation.

The Phase 1 agent should be fully usable with:

```text
DEMO_OBSERVABILITY=off
```

before this guide is implemented.

That separation is intentional: it ensures that telemetry remains an observer of behavior rather than a dependency of behavior.
