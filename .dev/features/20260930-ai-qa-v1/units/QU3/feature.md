# 20260930-ai-qa-v1/QU3: example scenarios and broken fixture branch

- Record schema: 4
- Status: MERGED
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: PR_UNIT
- Owner: cafitac (main task: Claude Code session)
- Repository: cafitac/preview-example-frontend (PR); cafitac/preview-example-backend (fixture branch)
- Created: 2026-09-30
- Updated: 2026-09-30
- Current slice: Q1 MacBook runner
- Current PR unit: QU3
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
- Authority grant: manifest 20260930-q1-v1 unit QU3 authority subset
- Approved delivery scope: manifest 20260930-q1-v1 unit QU3
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: QU3 PR in cafitac/preview-example-frontend (PR); cafitac/preview-example-backend (fixture branch) to main
- Delivery finalization evidence: user confirmation of manifest digest 1ee14a4e… on 2026-09-30
- Eligible unit IDs: QU3
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 7 (extended by QD8)
- Unit review topology map: QU3=INHERIT
- Unit review cycle budget map: QU3=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: a9324753c04be627202c7d33c53a2c16b41182dc
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/qu3-scenarios (feat/qu3-scenarios)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/units/QU3/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/preview-example-frontend/pull/9
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

qa/scenarios.yaml in the example frontend and the e2e-broken-add-note fixture branch in the example backend per manifest QU3.

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
  - QU3: feat/u10-pr-refs -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-q1-v1 unit QU3

## Open questions

- None.

## Progress and evidence

- 2026-09-30: Reserved and initialized by the main task: base a9324753c04be627202c7d33c53a2c16b41182dc, worktree /Users/reddit/Project/cafitac/.worktrees/qu3-scenarios.
- 2026-09-30: Worker (Codex) added qa/scenarios.yaml (2 scenarios), README section and a dependency-free Node check; worker ran lint/typecheck/test (52 vitest + 4 node)/build OK; main task validated the file against the QU1 scenario schema. Main task pushed fixture branch e2e-broken-add-note (919446a) in preview-example-backend: POST /api/notes always returns 500; main untouched. Review cycle 1 dispatched.
- 2026-09-30: Review cycle 1: reviewer-2 clean; reviewer-1 needs-evidence on backend ordering, seed texts and schema source — verified by the main task (backend list_notes orders created_at desc, id desc; seed.py texts 'Welcome to preview-hub!' and 'Try adding a note.'; schema = ai-qa schemas/scenario-file.schema.json, file validated against it) and recorded in the frontend README; lint-ok
type-ok
      Tests  52 passed (52) # pass 4 . Cycle 2 dispatched.
- 2026-10-01: Review cycle 2: reviewer-2 clean; reviewer-1 needs-evidence again (confined to this repository). Added in-repo evidence: vendored schema qa/scenario-file.schema.json (ai-qa 184afab, sha256 b7a76ebf…, byte-identical verified by the main task), VENDORED.md, schema-derived test rules, backend facts with commit 544fd35 in README; main-task npm test:       Tests  52 passed (52) # pass 5 . Cycle 3 dispatched.
- 2026-10-01: Review cycle 3: reviewer-2 clean; reviewer-1 needs-evidence (its session cannot run commands or read other repositories). Cycle 4 dispatched with attached verification evidence: commands (npm test, lint, typecheck, shasum of the vendored schema) and a cross-repository evidence file (ai-qa 184afab schema sha256; backend 544fd35 list_notes ordering and seed texts).
- 2026-10-01: Review cycle 4 (with evidence): reviewer-1 clean; reviewer-2 2 low findings (test stricter than the schema: UTF-16 line length, tag character set) fixed. Cycle 5 (last) dispatched with evidence.
- 2026-10-01: Review cycle 5: 3 low findings, all in the hand-written YAML checker. Under QD8 the test now parses with the yaml package and validates with ajv against the vendored schema (dev dependencies yaml, ajv installed by the main task). Cycle 6 dispatched with evidence.
- 2026-10-01: Review cycle 6 clean 2/2 with evidence (npm test, lint, typecheck, build exit 0; schema sha256 matches).
- 2026-10-01: PR #9 (preview-example-frontend) CI pass; squash-merged under D7 as 8d977155; worktree/branch removed. Fixture branch e2e-broken-add-note remains in preview-example-backend for QU4.
