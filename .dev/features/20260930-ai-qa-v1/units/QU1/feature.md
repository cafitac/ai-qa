# 20260930-ai-qa-v1/QU1: repository bootstrap and run core

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/ai-qa
- Created: 2026-09-30
- Updated: 2026-09-30
- Current slice: Q1 MacBook runner
- Current PR unit: QU1
- Delivery strategy: STANDALONE
- Current delivery bundle: N/A
- Bundle PR topology: N/A
- Architecture authoritative lifecycles: see parent control record
- Architecture durable effect families: see parent control record
- Architecture external authorities/gateways: see parent control record
- Architecture public idempotency namespaces: see parent control record
- Architecture runtime/deploy artifacts: see parent control record
- Architecture failure/recovery owners: see parent control record
- Architecture cleanup owners: see parent control record
- Architecture repositories/ledgers: see parent control record
- Architecture security/resource parsers: see parent control record
- Independent boundary categories: NONE
- Architecture split/replan decision: STANDALONE_REEVALUATED
- Failure/recovery owner map: see parent control record
- Cleanup inventory map: see parent control record
- Parent control record: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/feature.md
- Sprint ID: 20260930-q1-v1
- Sprint manifest: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/sprints/20260930-q1-v1.md
- Sprint manifest SHA-256: 1ee14a4e4c63a6854f0b28575dfb90daece1d565b4b5387951932e11bebc9090
- Authority grant: manifest 20260930-q1-v1 unit QU1 authority subset
- Approved delivery scope: manifest 20260930-q1-v1 unit QU1
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: QU1 PR in cafitac/ai-qa to main
- Delivery finalization evidence: user confirmation of manifest digest 1ee14a4e… on 2026-09-30
- Eligible unit IDs: QU1
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 10 (QD5, QD6; QD7 low-findings exception)
- Unit review topology map: QU1=INHERIT
- Unit review cycle budget map: QU1=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: ccaa70d77852aadddf59b7f759ad42c21a88a14e
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/qu1-core (feat/qu1-core)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/units/QU1/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/ai-qa/pull/1
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/design
- Design approval: parent control record, digest 82f3bbc855fc62e1d36e71f44bb811c7a0db7fe8a23c12d349161abd15a22d4e
- Design evidence identity: 82f3bbc855fc62e1d36e71f44bb811c7a0db7fe8a23c12d349161abd15a22d4e
- Service boundary E2E: N/A (live runs belong to QU4)
- Service boundary waiver: N/A
- Repository-wide checks: see Progress

## Workflow cursor

- Workflow stage: FEATURE_DEVELOP
- Last completed stage: CODE_PUSH
- Next eligible action: NONE (terminal)
- Next action class: LOCAL_CONTINUE
- Gate state: NONE
- Gate reason:
- Active run:
- Evidence identity:

## Outcome

Repository skeleton, contracts, Run core with fakes, report mapping and CLI per manifest QU1 (B1, B3, B5 unit level).

## Requirements

- See parent control record Q-R1–Q-R9; this unit's scope is in Outcome.

## Acceptance contract

- A9 live, A1-A6/A8 regression

## Design contract

- Profile decision: STANDARD, parent design approved (digest 084565e1…); this unit implements the listed contracts without changing them.

## Delivery map

### S3: Live PR bot E2E

- Status: IN_PROGRESS
- Outcome: see Outcome
- Included acceptance: A9 live, A1-A6/A8 regression
- Non-goals: anything outside the manifest unit scope
- Estimate: see manifest
- PR map:
  - QU1: feat/u10-pr-refs -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-q1-v1 unit QU1

## Open questions

- None.

## Progress and evidence

- 2026-09-30: Reserved and initialized by the main task: base ccaa70d77852aadddf59b7f759ad42c21a88a14e, worktree /Users/reddit/Project/cafitac/.worktrees/qu1-core.
- 2026-09-30: Worker (Codex) implemented QU1; main task ran uv sync (uv.lock created); ruff/format clean, pyright 0 errors, pytest 39 passed. Review cycle 1 dispatched.
- 2026-09-30: Review cycle 1: 10 findings (start URL control-char origin bypass, latest-run ordering, dead-pid states, REFUSED while RUNNING, refusal reason, decode errors, vendored-hash test, CI --locked, report-after-save, userinfo origins) fixed by the worker; 0 errors, 0 warnings, 0 informations | 70 passed in 2.02s. Cycle 2 dispatched.
- 2026-09-30: Review cycle 2: 5 findings (completion artifact ordering, OSError exit code, start URL base documented + multi-service test, utf-8 atomic write, show exit codes) fixed; 0 errors, 0 warnings, 0 informations | 86 passed in 2.07s. Cycle 3 dispatched.
- 2026-09-30: Review cycle 3: 3 low findings (printed state after recovery, trailing-newline pattern anchors, JSON descriptor parsing) fixed; 0 errors, 0 warnings, 0 informations | 96 passed in 2.76s. Cycle 4 dispatched.
- 2026-09-30: Review cycle 4: reviewer-2 clean; reviewer-1 6 low findings (pid validation, abort reason, OSError boundary labels, retry evidence isolation, expiresAt, start path wording) fixed plus a self re-read; 0 errors, 0 warnings, 0 informations | 123 passed in 3.35s. Cycle 5 (last in budget) dispatched.
- 2026-09-30: Review cycle 5: 3 findings (HIGH fixed-date test fixture vs real clock; descriptor timestamp parse -> invalid_descriptor; YAML timestamp coercion) fixed after the budget extension (QD5); 0 errors, 0 warnings, 0 informations | 139 passed in 4.13s. Cycle 6 dispatched.
- 2026-09-30: Review cycle 6: 3 low findings (RecursionError in gate, unencodable agent strings, single clock) fixed with a sweep; 0 errors, 0 warnings, 0 informations | 188 passed in 5.22s. Cycle 7 (last) dispatched.
- 2026-09-30: Review cycle 7: 4 low findings (auto-collected evidence URI validation, team domain/dashboard URL validation, show exit code for in-progress runs, dead code) fixed after QD6; 0 errors, 0 warnings, 0 informations | 209 passed in 5.48s. Cycle 8 dispatched.
- 2026-09-30: Review cycle 8: reviewer-2 clean; reviewer-1 2 low findings (retry archive name collision with agent-created files, empty env var handling) fixed; 0 errors, 0 warnings, 0 informations | 221 passed in 5.16s. Cycle 9 (last) dispatched.
- 2026-09-30: Review cycle 9: reviewer-2 clean; reviewer-1 3 low findings (refusal-handler save failure, evidence rule, COMPLETED without report) fixed under QD7; 0 errors, 0 warnings, 0 informations | 241 passed in 6.90s. Cycle 10 dispatched (merge if no HIGH/MEDIUM).
- 2026-10-01: Review cycle 10 (QD7): no HIGH/MEDIUM from either reviewer; pytest 241 passed, ruff/format/pyright clean. Merge gate met under QD7. Low findings carried into QU2 as required work items:
  - QU2-carry-1: a Refused with an allowed reason raised while RUNNING (agent boundary) is saved ABORTED without abort_reason and prints nothing — set abort_reason and assert it (aiqa/usecases.py except Refused branch).
  - QU2-carry-2: url_origin does not normalise default ports (https://host:443 vs https://host), so http evidence/origin comparison can fail for the same origin.
  - QU2-carry-3: between the COMPLETED save and the report write another process's `aiqa show` reports INTERRUPTED; with a live pid it should report in-progress (exit 5).
  - QU2-carry-4 (nit): .gitignore diff is only a trailing blank line.
- 2026-10-01: PR #1 CI pass; squash-merged under D7/QD7 as 184afab9; worktree/branch removed.
