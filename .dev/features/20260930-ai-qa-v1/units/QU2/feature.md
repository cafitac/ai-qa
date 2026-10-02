# 20260930-ai-qa-v1/QU2: agent and browser adapters, verdict gate, redaction

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
- Current PR unit: QU2
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
- Authority grant: manifest 20260930-q1-v1 unit QU2 authority subset
- Approved delivery scope: manifest 20260930-q1-v1 unit QU2
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: QU2 PR in cafitac/ai-qa to main
- Delivery finalization evidence: user confirmation of manifest digest 1ee14a4e… on 2026-09-30
- Eligible unit IDs: QU2
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 8 (QD9; QD10 low-findings exception)
- Unit review topology map: QU2=INHERIT
- Unit review cycle budget map: QU2=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 184afab969b01ce98235f421ea6fb5bc9996e25b
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/qu2-adapters (feat/qu2-adapters)
- Verification topology: LOCAL_LIGHT + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/units/QU2/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/ai-qa/pull/2
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

Claude/Codex agent runners, browser session (login, preflight), hub/GitHub sources, full VerdictGate, Redactor and doctor per manifest QU2 (B3 session refusal, B4, B5 unit level), plus the QU1 carry items QU2-carry-1..4.

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
  - QU2: feat/u10-pr-refs -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-q1-v1 unit QU2

## Open questions

- None.

## Progress and evidence

- 2026-10-01: Reserved and initialized by the main task: base 184afab969b01ce98235f421ea6fb5bc9996e25b, worktree /Users/reddit/Project/cafitac/.worktrees/qu2-adapters.
- 2026-10-01: Worker (Codex) implemented QU2 incl. the four QU1 carry items; main task ran uv lock/sync (playwright 1.63.0), installed Playwright Chromium; ruff/format/pyright clean, pytest 293 passed.
- 2026-10-01: Live smoke of the real Claude runner on a public page (agent call 1 of 40): exit 0, 8 turns, 111 s, valid JSON verdict, no orphan processes — but final.png was lost (Playwright MCP wrote it to the agent's temporary cwd). Worker fixed it by collecting validated image files from the temp cwd into the attempt directory; re-smoke (call 2 of 40): final.png present, 9 turns, 37 s; pytest 297 passed. Review cycle 1 dispatched with evidence.
- 2026-10-01: Review cycle 1: 7 findings (HIGH redaction false positives on short app cookies; stderr merged into the JSON stream; raw 404 ambiguity; late config/binary validation; JPEG evidence; state dir chmod; parser AttributeError) fixed; 0 errors, 0 warnings, 0 informations | 328 passed in 24.41s. Cycle 2 dispatched with evidence.
- 2026-10-01: Review cycle 2: 6 findings (agent isolation allow-list flags, recovery state RUNNING, summary notes placement, UTF-8 scenario + index-based checks, single pin regex, Playwright errors in login/doctor) fixed; pytest 345 passed; live smoke 3 with the isolation flags OK (6 turns, 34 s, final.png kept; call 3 of 40). Cycle 3 dispatched with evidence.
- 2026-10-01: Review cycle 3: reviewer-1 produced no receipt (API 529 Overloaded, transient; not a verdict); reviewer-2 4 findings (non-http navigation -> out_of_scope, elapsed time excludes cleanup, symlink rule, GitHub rate limit vs not-public) fixed; 0 errors, 0 warnings, 0 informations | 377 passed in 21.43s. Cycle 4 dispatched with evidence.
- 2026-10-01: Review cycle 4: 3 findings (HIGH symlink check walked ancestors above the attempt dir; redaction skipped on abort paths; show RUNNING view printed abort_reason) fixed with a sweep; 0 errors, 0 warnings, 0 informations | 383 passed in 21.61s. Cycle 5 (last) dispatched with evidence.
- 2026-10-01: Review cycle 5: reviewer-1 clean; reviewer-2 1 medium finding (GitHub scenario source YAML loader mismatch) fixed with shared parse helpers after QD9; 0 errors, 0 warnings, 0 informations | 396 passed in 22.38s. Cycle 6 dispatched with evidence.
- 2026-10-01: Review cycle 6: reviewer-1 clean; reviewer-2 1 low finding (GitHub API redirect for renamed repositories misclassified) fixed; 0 errors, 0 warnings, 0 informations | 415 passed in 22.68s. Cycle 7 (last) dispatched with evidence.
- 2026-10-01: Review cycle 7: reviewer-2 clean; reviewer-1 1 low finding (screenshot collection listing errors escape the finally) fixed under QD10; 0 errors, 0 warnings, 0 informations | 431 passed in 22.40s. Cycle 8 dispatched (merge if no HIGH/MEDIUM).
- 2026-10-01: Review cycle 8 clean 2/2 (pytest 431 passed). P4 notes carried into QU4: (a) PlaywrightSession.close() should attempt every temp-state unlink before raising, plus a test for the cleanup-failure path; (b) README wording "scanned for cookies" should say Access cookies (or include all long cookie values); (c) README "rejects reported cap violations" should say turn cap only.
- 2026-10-01: PR #2 CI pass; squash-merged under D7 as 0ee478ac; worktree/branch removed.
