# Planner / Executor protocol

Use these structures as lightweight contracts. They may live in the agent's task system,
scratchpad, or messages; creating state files in the user's repository is not required.

## Workflow state

```yaml
goal: User-visible outcome
acceptance_criteria:
  - Observable criterion
concurrency_limit: 4
max_planning_rounds: 3
round: 1
branches: []
integration_status: pending
```

Allowed branch states:

- `planned`
- `ready`
- `running`
- `succeeded`
- `failed`
- `blocked`
- `cancelled`

## Branch plan

```yaml
id: api-contract
objective: Add the validated API request and response contract
depends_on: []
ownership:
  - src/api/schema.ts
  - tests/api/schema.test.ts
inputs:
  - Existing endpoints use Zod schemas
deliverable:
  - New schema exported through the existing module boundary
  - Edge cases covered by focused tests
verification:
  - npm test -- tests/api/schema.test.ts
write_access: edit
risk: medium
status: ready
```

Ownership can be concern-based for read-only investigation. Edit branches should use concrete
file or directory boundaries whenever possible.

## Executor prompt

```text
User goal:
<original desired outcome>

Your branch:
<id and objective>

Working context:
<repository path, language, known conventions>

Dependencies and evidence:
<relevant predecessor results and inspected facts>

Ownership:
<allowed files/directories or read-only concerns>
Do not modify anything outside this boundary. If that boundary is insufficient, stop and explain why.

Deliverable:
<observable output>

Verification:
<focused checks>

Return:
- status: succeeded | failed | blocked
- summary
- changed files
- checks run with results
- evidence or key decisions
- remaining risks or blocker

Do not commit, push, deploy, publish, or broaden scope unless the user explicitly authorized it.
```

## Executor result

```yaml
branch_id: api-contract
status: succeeded
summary: Added and exported the request/response schemas with invalid-input coverage.
changed_files:
  - src/api/schema.ts
  - tests/api/schema.test.ts
checks:
  - command: npm test -- tests/api/schema.test.ts
    result: passed
evidence:
  - Existing error envelope preserved
risks: []
```

A read-only branch replaces `changed_files` with inspected paths and concrete findings.

## Dependency scheduling

At each round:

1. Mark a planned branch `ready` when every `depends_on` branch succeeded.
2. Dispatch ready branches up to `concurrency_limit`.
3. Collect all completed results before selecting the next set.
4. If a dependency failed:
   - mark children `blocked`, or
   - revise only those children when an alternate input exists.
5. Stop after `max_planning_rounds` unless the user requests deeper exploration.

## Failure semantics

- One branch fails: preserve successful siblings and assess whether the failed branch is required.
- All ready branches fail: stop and report the shared blocker; do not claim partial work as complete.
- Verification fails after edits: the owning Executor gets one evidence-based repair attempt.
- Integration verification fails: the Integrator identifies the owning branch or interface and performs
  a targeted repair; do not rerun every branch blindly.
- Definitive permission or authentication denial: report it once and stop that branch.

## Integration checklist

- [ ] Acceptance criteria are satisfied.
- [ ] Every changed file has a clear owning branch or integration reason.
- [ ] Parallel branches did not silently overwrite each other.
- [ ] Shared interfaces agree across branches.
- [ ] Targeted checks passed.
- [ ] Broader checks were run when shared behavior changed.
- [ ] No secrets or unrelated artifacts were introduced.
- [ ] Documentation describes the implemented behavior.
- [ ] Unresolved failures and risks are disclosed.
