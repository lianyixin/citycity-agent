---
name: citycity-planner-executor
description: Plans complex engineering work as diverse dependency-aware branches, dispatches bounded parallel executor agents, isolates branch failures, and integrates verified results. Use for multi-file features, refactors, migrations, investigations, or other work that benefits from explicit planning and parallel execution; skip for small single-step edits.
license: MIT
compatibility: Works with coding agents that can inspect and edit a repository. Parallel execution is optional; agents without subagent support must execute ready branches sequentially.
metadata:
  author: citycity-agent
  version: "1.0.0"
  source: https://github.com/lianyixin/citycity-agent
---

# CityCity Planner / Executor

Apply CityCity Agent's fan-out and bounded-execution pattern to software engineering tasks.
Separate planning from execution: the Planner defines verifiable branches, Executors own
those branches, and the Integrator validates the combined result.

## Core rules

1. Inspect before planning. Ground the plan in repository evidence.
2. Preserve the user's scope. Do not turn implementation into unrelated cleanup.
3. Make branches outcome-oriented, independently verifiable, and as non-overlapping as possible.
4. Respect dependencies. Dispatch only branches whose prerequisites are complete.
5. Bound concurrency. Use at most 4 concurrent Executors unless the environment or user sets a lower limit.
6. Give every Executor an explicit ownership boundary and result contract.
7. Isolate failures. Keep successful branches when one branch fails.
8. Integrate centrally. Executors do not declare the overall task complete.
9. Verify the combined state, not only each branch in isolation.
10. Never commit, push, publish, deploy, or perform another external side effect unless the user authorized it.

Read [references/protocol.md](references/protocol.md) before dispatching work. Read
[references/examples.md](references/examples.md) when branch boundaries are unclear.

## Phase 1: Frame the request

Classify the request:

- **Answer / review / diagnose**: gather evidence and return findings; do not edit unless asked.
- **Change / build**: implement and verify the requested result.
- **Plan only**: stop after presenting the plan.

Extract:

- desired outcome and acceptance criteria;
- in-scope and out-of-scope areas;
- repository constraints and user instructions;
- risky or irreversible actions requiring confirmation;
- likely verification commands.

If one small edit can be completed and verified directly, do not fan out. Use this workflow
only when decomposition reduces latency, context load, or risk.

## Phase 2: Planner

Inspect relevant code, tests, configuration, and documentation. Then produce a branch graph
with 2–6 branches. Prefer diverse responsibilities rather than several agents exploring the
same question.

Each branch must define:

- `id`: stable short identifier;
- `objective`: one concrete outcome;
- `depends_on`: prerequisite branch IDs;
- `ownership`: files, directories, or concerns this branch may change;
- `inputs`: evidence and decisions already known;
- `deliverable`: code, findings, tests, or documentation expected;
- `verification`: focused checks for this branch;
- `write_access`: `read-only` or `edit`;
- `risk`: `low`, `medium`, or `high`.

Before dispatch, reject or revise branches that:

- duplicate another branch's objective;
- allow conflicting edits to the same files without an explicit sequence;
- have no observable completion condition;
- depend on an unresolved product decision;
- require a side effect outside the user's authorization.

Keep integration and final verification as Planner-owned work unless a dedicated integration
branch is necessary.

## Phase 3: Dispatch ready branches

Select branches whose dependencies are satisfied. Dispatch up to the concurrency limit.

Use the host agent's native subagent, task, worktree, or delegation feature when available.
Do not assume vendor-specific tool names. If parallel delegation is unavailable, execute the
same ready branches sequentially and preserve their contracts.

Every Executor prompt must be self-contained and include:

1. the user goal;
2. the branch objective;
3. repository path or working context;
4. ownership and write-access boundaries;
5. relevant evidence and prerequisite results;
6. expected deliverable and verification;
7. instructions to report changed files, checks run, failures, and remaining risks;
8. instructions not to commit, push, or broaden scope unless explicitly authorized.

For parallel edit branches, require disjoint file ownership. If two branches must touch the
same file, sequence them or make one read-only.

## Phase 4: Execute

Each Executor follows this loop:

1. Confirm the branch can be completed within its ownership boundary.
2. Inspect the minimum additional context needed.
3. Implement or investigate only the assigned objective.
4. Run the narrowest meaningful verification.
5. Re-read the diff or evidence for accidental scope expansion.
6. Return the result contract from `references/protocol.md`.

An Executor must stop and report a blocker when:

- a required user decision materially changes the implementation;
- credentials, permissions, or external access are definitively unavailable;
- ownership boundaries make the requested change unsafe;
- repository evidence contradicts the Planner's assumptions.

The Planner may revise and redispatch a failed branch once when new evidence provides a
specific correction. Do not repeat the same failed attempt without a changed hypothesis.

## Phase 5: Collect and expand

As branches finish:

1. Validate each result against its deliverable and ownership.
2. Record successful outputs even if another branch failed.
3. Unblock dependent branches using concrete predecessor results.
4. Re-plan only the affected portion of the graph.
5. If all branches for a required outcome fail, stop integration and report the root blocker.

Optional recursive expansion is allowed when a result reveals a necessary next step. A child
branch must:

- cite the parent result that created it;
- stay within the original user scope;
- have a bounded depth (default maximum: 3 planning rounds);
- satisfy the same branch contract as an initial branch.

Do not recursively create "nice to have" work.

## Phase 6: Integrate

The Planner acts as Integrator:

1. Inspect all Executor results and repository changes.
2. Resolve interface mismatches and overlapping assumptions.
3. Ensure documentation matches actual behavior.
4. Run repository-level checks appropriate to the risk:
   - targeted tests for changed behavior;
   - lint or type checks for edited files;
   - broader tests or builds when shared interfaces changed.
5. Review the final diff for unrelated changes, secrets, generated artifacts, and missing tests.
6. Compare the result with the original acceptance criteria.

Do not hide partial failure. If a non-critical branch failed, state what succeeded, what did
not, and whether the requested outcome is still complete.

## Final response

Lead with the outcome. Include:

- what was completed;
- important design choices;
- verification performed and its result;
- unresolved blockers or risks;
- any user action still required.

Keep internal orchestration detail brief unless the user asks for it. Never claim a check
passed unless there is execution evidence.
