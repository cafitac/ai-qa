# 20260930-ai-qa-v1/QU4: live runs and README

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
- Current PR unit: QU4
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
- Authority grant: manifest 20260930-q1-v1 unit QU4 authority subset
- Approved delivery scope: manifest 20260930-q1-v1 unit QU4
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: QU4 PR in cafitac/ai-qa to main
- Delivery finalization evidence: user confirmation of manifest digest 1ee14a4e… on 2026-09-30
- Eligible unit IDs: QU4
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: QU4=INHERIT
- Unit review cycle budget map: QU4=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repository; main is the only integration branch.
- Initialization base SHA: 0ee478ac9bf14ba990b054ee02158aa941ebfa6d
- Worktree/branch: /Users/reddit/Project/cafitac/.worktrees/qu4-live (feat/qu4-live)
- Verification topology: LOCAL_LIGHT + LIVE_RUN + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope)
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: REMOVED
- Canonical record: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/units/QU4/feature.md
- Record provenance: Created by the sprint main task at reservation; the unit record stays in the control repository's .dev (canonical source), linked to the worktree.
- External links: https://github.com/cafitac/ai-qa/pull/3
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

e2e/live.sh live runs (B1–B5) against preview-hub environments and README per manifest QU4, plus QU2 P4 carry notes (temp-state cleanup attempts all unlinks; README wording for redaction scope and caps).

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
  - QU4: feat/u10-pr-refs -> main
- QA checkpoint: unit tests + CI; runtime E2E in U4
- Rollout/rollback: no deployment; revert

## Safety and rollout

- Release state: N/A
- Activation mode: N/A

## Decisions and assumptions

### D1: Scope from manifest

- Status: CONFIRMED
- User answer: 응 이 범위로 확정하고 시작해줘 (2026-09-29)
- Normalized value: manifest 20260930-q1-v1 unit QU4

## Open questions

- None.

## Progress and evidence

- 2026-10-01: Reserved and initialized by the main task: base 0ee478ac9bf14ba990b054ee02158aa941ebfa6d, worktree /Users/reddit/Project/cafitac/.worktrees/qu4-live.
- 2026-10-02: First owner `aiqa login` was refused by the HttpOnly check (as designed). A names/flags-only diagnostic (no values printed or saved) showed the app-host CF_Authorization was not HttpOnly, and that the browser state also carried github.com session cookies from the SSO hop. With the user's approval the agent enabled "HTTP Only" in the Cloudflare Access app cookie settings (saved: "Application successfully configured"). Code fix added to QU4: persist only Access-related cookies.
- 2026-10-02: Owner re-ran `aiqa login` from the QU4 worktree: "session saved (4 Access cookies)"; doctor: session present (0600).
- 2026-10-02: Live run 1 of e2e/live.sh (exit 0, 5 agent calls): B3 missing env REFUSED environment_not_ready with 0 calls; B1 main/main both scenarios PASSED (seed 4 turns 93 s, add-note 9 turns 32 s), report schema/screenshots/commits verified; B2 broken backend: seed PASSED, add-note FAILED by the agent verdict (agent observed the app alert "Could not confirm the note was saved..." and the note missing); B4 secret scan 0 matching files in all run directories; B5 max_turns 1 -> turn_cap, run COMPLETED; cleanup inventories empty. Evidence: evidence/live-run1.log and per-run run.json/report.json/summary.md (screenshots kept in the worktree runs/ only).
- 2026-10-02: Review cycle 1 dispatched with evidence (pytest/ruff/pyright, sh -n, live run log).
- 2026-10-02: Review cycle 1: findings (live config generator dropped environment_domain; dead parent-domain branch in the login cookie check) fixed; 0 errors, 0 warnings, 0 informations | 451 passed in 27.35s. Cycle 2 dispatched with evidence.
- 2026-10-02: Review cycle 2: findings (live check must pin the Claude adapter and clamp scenarios/retries; reservation computed before each run) fixed; 0 errors, 0 warnings, 0 informations | 454 passed in 23.26s. Cycle 3 dispatched with evidence.
- 2026-10-02: Review cycle 3 clean 2/2 (pytest 454 passed). P4 follow-ups (not blocking, recorded for Q2/Q3 planning): (a) preflight state filter uses a fixed host shape; consider allowing the descriptor's own origins or refusing when the entry host is outside the filter; (b) the live config clamps max_scenarios/max_turns with min(owner, N) — pin to what B1/B2 need or refuse up front when below.
- 2026-10-02: PR #3 CI pass; squash-merged under D7 as 62782339; worktree/branch removed; live run directories (with screenshots) moved to the main checkout runs/ (git-ignored).
