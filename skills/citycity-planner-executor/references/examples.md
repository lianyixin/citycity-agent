# Decomposition examples

Use these patterns when deciding whether branches are independent enough to execute in parallel.

## Multi-file feature

Request: add an authenticated export endpoint and UI action.

```yaml
branches:
  - id: inspect-contracts
    objective: Identify existing auth, API, and export conventions
    depends_on: []
    ownership: [backend, frontend]
    write_access: read-only

  - id: backend-export
    objective: Implement the authenticated export endpoint
    depends_on: [inspect-contracts]
    ownership: [backend/app/export.py, backend/tests/test_export.py]
    write_access: edit

  - id: frontend-action
    objective: Add the export action against the agreed API contract
    depends_on: [inspect-contracts]
    ownership: [frontend/src/export, frontend/src/components/ExportButton.tsx]
    write_access: edit

  - id: docs
    objective: Document export usage and configuration
    depends_on: [backend-export, frontend-action]
    ownership: [README.md]
    write_access: edit
```

The backend and frontend branches run in parallel only after the contract investigation. The
Integrator verifies the end-to-end interface after both complete.

## Refactor with shared interfaces

Request: replace a storage adapter across the application.

Good decomposition:

1. Read-only inventory of the current interface and callers.
2. Adapter implementation and adapter-focused tests.
3. Caller migration, dependent on the finalized adapter interface.
4. Integration tests and documentation.

Do not run steps 2 and 3 in parallel if both would edit the shared interface. Sequence the
interface decision first.

## Investigation

Request: diagnose intermittent CI failures.

Create diverse read-only branches:

- analyze failing logs and timing patterns;
- inspect tests for shared mutable state;
- inspect recent dependency or environment changes.

The Integrator compares evidence and chooses the strongest root-cause hypothesis. Do not ask
three Executors to perform the same unrestricted investigation.

## Small task: skip fan-out

Request: fix one typo in a README heading.

Edit and verify directly. Planning and delegation would add overhead without reducing risk.

## Unsupported parallelism

When the host agent cannot launch subagents:

1. Keep the same branch graph.
2. Execute ready branches one at a time.
3. Record each result before starting a dependent branch.
4. Preserve ownership boundaries to avoid accidental scope expansion.

The workflow remains useful because planning, failure isolation, and integration do not depend
on a specific agent vendor.
