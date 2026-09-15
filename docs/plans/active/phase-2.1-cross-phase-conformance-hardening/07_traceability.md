# Traceability

## Guide to requirements

| Guide area | Requirements |
|---|---|
| §7.4 input/result contracts | `C21-REQ-002`, `C21-REQ-003` |
| §7.3 opaque sessions | `C21-REQ-011`–`C21-REQ-013` |
| §8 configuration and immutability | `C21-REQ-007`–`C21-REQ-010` |
| §9 profile matrix | `C21-REQ-001`, `C21-REQ-009` |
| §15 lifecycle and streaming | `C21-REQ-004`–`C21-REQ-006` |
| Phase 2 catalog/structured contracts | `C21-REQ-007`–`C21-REQ-010`, `C21-REQ-014`–`C21-REQ-016` |

## Requirements to tasks, criteria and validation

| Requirement | Tasks | Criteria | Validation |
|---|---|---|---|
| `C21-REQ-001`–`003` | `0002` | `002`–`004` | core unit tests |
| `C21-REQ-004`–`006` | `0003` | `005`–`009` | runner/lifecycle contract tests |
| `C21-REQ-007`–`010` | `0004` | `010`–`015` | config/resolution/concurrency tests |
| `C21-REQ-011`–`013` | `0005` | `016`–`021` | session trust/migration tests |
| `C21-REQ-014`–`015` | `0006` | `009`, `022`, `023` | fake parity and semantic suite |
| `C21-REQ-016`–`017` | `0001`, `0007`, `0008` | `001`, `024`–`029` | integration, packaging, docs and CI |

