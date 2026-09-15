# ADR 0003 — Host-managed tools

## Estado

Accepted for Phase 5 and released with `0.6.0` after owner review.

## Context

Provider models need a narrow way to request host capabilities without receiving
callables, credentials, filesystem authority, or provider objects. Codex dynamic
tools are experimental in the pinned SDK and cannot become part of the neutral
runtime contract.

## Decision

Proteo exposes immutable definitions, requests, results, registries, and executors
under `proteo_runtime.tools`. The host owns executable bindings and exact permission
checks. Approval is asynchronous and fail-closed; the default failure policy returns
sanitized errors to the model. Retries are bounded and only available to explicitly
idempotent tools. Deduplication is in-memory and scoped to one invocation.

Codex integration is isolated under `proteo_runtime.providers.codex.experimental`,
requires an explicit feature flag and a compatibility probe, and uses only private SDK
hooks. Native tools, shell, writable filesystem, network, browser, and MCP authority
remain disabled. No callable, permission, approval, result, or cache is persisted.

## Consequences

The neutral package remains provider-independent and can be tested without network or
subscription quota. The experimental adapter must be revisited whenever the Codex SDK
wire or private hooks change; incompatibility fails before inference instead of
falling back to prompt parsing.
