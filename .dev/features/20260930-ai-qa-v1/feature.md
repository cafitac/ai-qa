# 20260930-ai-qa-v1: ai-qa — AI-driven E2E on preview environments

- Record schema: 4
- Status: IN_PROGRESS
- Planning mode: STANDARD
- Execution mode: AUTONOMOUS_SPRINT
- Record kind: SPRINT_CONTROL
- Owner: cafitac (personal project)
- Repository: cafitac/ai-qa (new); example scenarios in cafitac/preview-example-frontend
- Created: 2026-09-30
- Updated: 2026-09-30
- Current slice: Q1 MacBook runner (sprint 20260930-q1-v1)
- Current PR unit: CONTROL
- Delivery strategy: STANDALONE
- Current delivery bundle: N/A
- Bundle PR topology: N/A
- Architecture authoritative lifecycles: QA run lifecycle owned by ai-qa (unknown detail until design); environment lifecycle stays in preview-hub
- Architecture durable effect families: report and evidence files on the runner host; PR comments (Q3)
- Architecture external authorities/gateways: preview-hub (descriptor, read-only), agent CLI (Claude Code / Codex subscription), Playwright browser, GitHub (scenario files at pinned commits, PR diff), Cloudflare Access (session)
- Architecture public idempotency namespaces: run id per (environment, commits, scenario set) — unknown detail until design
- Architecture runtime/deploy artifacts: ai-qa CLI on the MacBook (Q1); container in the preview-hub VM (Q3)
- Architecture failure/recovery owners: unknown until design
- Architecture cleanup owners: unknown until design
- Architecture repositories/ledgers: run ledger (files or SQLite) — unknown until design
- Architecture security/resource parsers: descriptor parser, scenario file parser, navigation allowlist, agent output parser
- Independent boundary categories: runtime-artifact, failure/recovery-owner
- Architecture split/replan decision: STANDALONE_REEVALUATED
- Failure/recovery owner map: create/update/delete failures owned by hub lifecycle; partial-create cleanup by runner (design input)
- Cleanup inventory map: per-environment Compose project, network, volumes, DB, proxy route, built images, workspace checkouts (design input)
- Parent control record: N/A (this record is the sprint control record)
- Sprint ID: 20260930-q1-v1
- Sprint manifest: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/sprints/20260930-q1-v1.md
- Sprint manifest SHA-256: 1ee14a4e4c63a6854f0b28575dfb90daece1d565b4b5387951932e11bebc9090
- Authority grant: manifest 20260930-q1-v1 authority matrix + REPO_CREATE + E2E_FIXTURES + LIVE_RUN + MERGE (D7), confirmed by the user 2026-09-30
- Approved delivery scope: QU1–QU4 per manifest 20260930-q1-v1; merge by main task under D7
- Delivery finalization: AUTO_AFTER_GATES
- Delivery finalization scope: QU1–QU4 PRs in cafitac/ai-qa and cafitac/preview-example-frontend (main)
- Delivery finalization evidence: user confirmation 2026-09-30 "응 이 범위로 확정하고 시작해줘" for manifest digest 1ee14a4e4c63a6854f0b28575dfb90daece1d565b4b5387951932e11bebc9090
- Eligible unit IDs: QU1, QU2, QU3, QU4
- Review topology: CODE_POLISH_QUORUM
- Review quorum: 2
- Review scheduling: PARALLEL
- Review cycle budget: 5
- Unit review topology map: QU1=INHERIT, QU2=INHERIT, QU3=INHERIT, QU4=INHERIT
- Unit review cycle budget map: QU1=INHERIT, QU2=INHERIT, QU3=INHERIT, QU4=INHERIT
- Single-reviewer exception scope: N/A
- Single-reviewer exception rationale: N/A
- Single-reviewer exception approval: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: New personal repositories; main is the only integration branch (no develop, no deployment coupling).
- Initialization base SHA: pending
- Worktree/branch: not created
- Verification topology: LOCAL_LIGHT + RUNTIME_HOST_E2E + CI_EXACT_SHA
- Execution plane: LOCAL (personal scope); runtime host for Docker environments and E2E is trading-macstudio (user decision 2026-09-29)
- Remote test runner profile: N/A
- Remote test fallback: USER_OPT_IN
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree cleanup status: NOT_CREATED
- Worktree cleanup evidence:
- Canonical record: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/feature.md
- Record provenance: Created by feature-plan on 2026-09-30 before the repository exists; no worktree handoff has occurred yet.
- External links: none yet
- Design profile: STANDARD
- Design status: APPROVED
- Design root: /Users/reddit/Project/cafitac/ai-qa/.dev/features/20260930-ai-qa-v1/design
- Design approval: APPROVED by user 2026-09-30 ("승인할게 진행해줘") for digest 82f3bbc855fc62e1d36e71f44bb811c7a0db7fe8a23c12d349161abd15a22d4e (revalidated unchanged)
- Design evidence identity: artifact_set_sha256 82f3bbc855fc62e1d36e71f44bb811c7a0db7fe8a23c12d349161abd15a22d4e
- Service boundary E2E: RUNTIME E2E against a live preview-hub environment (example frontend + backend)
- Service boundary waiver: N/A
- Repository-wide checks: to be defined at repository creation (ruff, pyright, pytest)

## Workflow cursor

- Workflow stage: FEATURE_PLAN
- Last completed stage: FEATURE_PLAN_PROVISIONAL
- Next eligible action: AGENT_SQUAD (run sprint 20260930-q1-v1)
- Next action class: LOCAL_CONTINUE
- Gate state: NONE
- Gate reason:
- Active run:
- Evidence identity:

## Autonomous sprint

- Sprint state: SPRINT_COMPLETE
- Manifest version: 1 (Q1)
- Manifest confirmation: user, 2026-09-30, "응 이 범위로 확정하고 시작해줘", digest 1ee14a4e4c63a6854f0b28575dfb90daece1d565b4b5387951932e11bebc9090 re-hashed unchanged
- Planning base SHA: ai-qa bootstrap ccaa70d77852aadddf59b7f759ad42c21a88a14e; preview-example-frontend a9324753c04be627202c7d33c53a2c16b41182dc; preview-example-backend 544fd35e612f9751547e650f50ab0a5f1d5b1567
- Base drift policy: ALLOW_IF_DISJOINT
- Execution base SHA: ai-qa ccaa70d77852aadddf59b7f759ad42c21a88a14e
- Started: 2026-09-30 (Q1)
- Expires: 2026-10-10 23:59 KST
- Desired finish state: MERGED (D7)
- Learning mode: PROPOSE
- WIP / unit / repair / retry budgets: WIP 2 / units 4 / repair 2 (+3 runtime) per unit / CI retry 2 (consumed: 0); product agent calls 40 (consumed: 8; the design spike call is not counted)
- Setup reservations: none (converted to claims)
- Active PR units: none
- Remaining eligible units: QU1=MERGED 184afab9, QU2=MERGED 0ee478ac, QU3=MERGED 8d977155 (frontend), QU4=MERGED 62782339
- Authority matrix: see manifest
- Selection rule: QU1; QU3 in parallel; QU2 after QU1; QU4 last
- Stop and escalation: see manifest
- Boundary decision: Q1 complete 2026-10-02; B1–B5 proven live (AI caught the broken add-note; 8 product agent calls of 40); next: Q2 (PR-diff scenario proposals) or Q3 (VM automation + /qa) need planning

## Outcome

Given a READY preview-hub environment, one command runs natural-language E2E scenarios written in the service repositories through an AI agent that drives a real browser, and produces a `qa-report/v1` report with evidence that records the exact commits tested. Later the same runner works from a PR comment inside the preview-hub VM.

## Requirements

- Q-R1 [MUST]: Consume `environment-descriptor/v1` from preview-hub; run only against state READY and readiness.allHealthy; record the descriptor commits in the report.
- Q-R2 [MUST]: Scenarios are natural-language files in each service repository (`qa/scenarios.yaml`: id, title, steps, expected result, tags), read at the environment's pinned commit of that service.
- Q-R3 [MUST]: An agent CLI on a subscription login (Claude Code headless by default; Codex selectable) drives a real browser through Playwright (Playwright MCP) and returns a verdict PASSED/FAILED/SKIPPED per scenario with evidence (screenshots, final URL, console/network errors, agent summary). The browser driver and the agent CLI sit behind interfaces so another driver can be added later.
- Q-R4 [MUST]: Output `qa-report/v1` (validates against the preview-hub schema) plus a human-readable summary; non-zero exit when any scenario FAILED.
- Q-R5 [MUST]: Safety and budget: navigation limited to hosts in the descriptor; no credentials in prompts, reports or logs; caps counted in agent calls/turns and wall time per scenario and per run; synthetic data only.
- Q-R6 [SHOULD] (Q2): From a PR diff the AI proposes additional scenarios; proposals are written to the report only and never executed automatically.
- Q-R7 [MUST] (Q1): Runs on the MacBook as `aiqa run <env>`; passes Cloudflare Access with a browser session the owner logs into once (`aiqa login`, persisted Playwright state); no service token and no preview-hub change in Q1.
- Q-R8 [SHOULD] (Q3): Runs as a container in the preview-hub VM triggered by `/qa` in a PR comment (and later the dashboard), replying with one summary comment; needs an Access service token, a preview-hub change to accept service identities, and a long-lived agent CLI token installed by the owner.
- Q-R9 [OUT_OF_SCOPE]: metered model APIs or any paid service; Earlypay code, rules or data; the Aside browser (kept possible through the driver interface, not built).

## Acceptance contract

- B1 (Q-R1..R4, R7): With a READY environment of the example services and two scenarios in the example frontend repository ("seed notes are listed", "adding a note shows it first"), `aiqa run <env>` produces a report that validates against `qa-report/v1`, both PASSED, screenshots present, commits equal to the descriptor. Evidence: automated tests with fake agent/browser + live run.
- B2 (Q-R3, R4): Against an environment built from a branch where adding a note is broken, that scenario is FAILED with a reason and evidence, the other still runs, exit code is non-zero. Evidence: live run.
- B3 (Q-R1): A non-READY, unhealthy or unknown environment is refused before any agent call. Evidence: automated tests.
- B4 (Q-R5): A scenario that tries to leave the descriptor hosts is blocked and reported; no token, cookie or JWT appears in the report or logs. Evidence: automated tests + log scan in the live run.
- B5 (Q-R5): A scenario exceeding its turn or time cap is FAILED(timeout) and the run continues; total agent calls stay within the run cap. Evidence: automated tests with a fake agent.
- B6 (Q-R6, Q2): Given a PR diff, the report lists proposed scenarios marked as not executed. Evidence: automated tests + one live run.
- B7 (Q-R8, Q3): `/qa` on a PR runs in the VM and posts exactly one summary comment. Evidence: live PR.

## Design contract

- Profile decision: STANDARD — new run lifecycle, several external boundaries (hub descriptor, agent CLI, browser, GitHub), credentials/session handling and a public report contract; no money or irreversible data.
- Required artifacts: context map; domain model (Run, Scenario, Verdict, Evidence, interfaces AgentRunner and BrowserDriver); run state machine and failure rules; consistency (idempotent run id, partial results, cleanup of browser/agent processes); interface contracts (scenario file schema, CLI, agent prompt/result contract, report mapping to qa-report/v1, Access session handling); acceptance trace; Korean review pack.

## Delivery map

### Q1: MacBook runner

- Status: PLANNING (design first)
- Outcome: B1–B5
- Estimate: 3–5 days engineering; confidence medium (agent CLI + Playwright MCP behaviour must be proven early)

### Q2: PR-diff scenario proposals

- Status: PLANNED (coarse)
- Outcome: B6
- Estimate: 1–2 days

### Q3: VM automation and PR comment

- Status: PLANNED (coarse)
- Outcome: B7; includes a preview-hub change (service identities) and owner-installed tokens
- Estimate: 2–4 days

- Delivery bundles: none
- QA checkpoint: live run against a preview-hub environment per slice
- Rollout/rollback: personal repositories; no deployment in Q1 (local CLI). Reports are files; delete to roll back.

## Safety and rollout

- No paid services or metered API calls; agent usage is bounded by call/turn caps.
- The owner logs in to Access and the agent CLI; the agent never reads, prints or stores credential values.
- No Earlypay code, configuration or credentials.

## Decisions and assumptions

### QD1: Browser control

- Status: CONFIRMED
- User answer (2026-09-30): AI drives the browser directly; Aside was mentioned as well regarded, but Playwright is considered sufficient.
- Normalized value: agent CLI + Playwright (Playwright MCP); driver behind an interface; Aside not built (desktop AI browser for personal automation, unpublished pricing).
- Confirmed at: 2026-09-30

### QD2: Scenario source

- Status: CONFIRMED
- User answer (2026-09-30): "작성 + AI 추가 제안"
- Normalized value: repository-authored natural-language scenarios always run; AI proposals from PR diffs are suggestions only.
- Confirmed at: 2026-09-30

### QD3: Runner location

- Status: CONFIRMED
- User answer (2026-09-30): "MacBook 먼저, 그다음 VM"
- Normalized value: Q1 on the MacBook with a persisted Access browser session; Q3 moves to a VM container with service token and hub change.
- Confirmed at: 2026-09-30

### QD4: Process

- Status: CONFIRMED
- User answer (2026-09-30): "같게 (권장)"
- Normalized value: STANDARD design, autonomous within the approved scope, 2 Claude reviewers, agent merges cafitac PRs after gates (D7 carried over), repository cafitac/ai-qa in Python.
- Confirmed at: 2026-09-30

### QD5: QU1 review budget extension

- Status: CONFIRMED
- User answer (2026-09-30): "예산 2회차 연장 (권장)" to the budget-exhaustion packet (cycle 5: one HIGH test time bomb from the cycle-4 repair and two LOW findings).
- Normalized value: QU1 review cycle budget raised from 5 to 7 (QU1 only); the 2-of-2 clean quorum gate is unchanged.
- Confirmed at: 2026-09-30

### QD6: QU1 review budget second extension

- Status: CONFIRMED
- User answer (2026-09-30): "4건 고치고 2회차 더 (권장)" to the second budget-exhaustion packet (cycle 7: four LOW findings, no HIGH/MEDIUM since cycle 5).
- Normalized value: QU1 review cycle budget raised from 7 to 9 (QU1 only); the 2-of-2 clean quorum gate is unchanged.
- Confirmed at: 2026-09-30

### QD7: QU1 merge gate exception (low findings tolerated once)

- Status: CONFIRMED
- User answer (2026-09-30): "3건 고치고 낮은 등급은 허용 (권장)" to the third budget-exhaustion packet (cycle 9: reviewer-2 clean in cycles 8 and 9; reviewer-1 three LOW findings; no HIGH/MEDIUM since cycle 5).
- Normalized value: for QU1 only — fix the three findings, run one more review cycle (cycle 10); merge if neither reviewer reports a HIGH or MEDIUM finding; any new LOW findings are recorded in the QU1 record and become required work items of QU2. From QU2 on the 2-of-2 clean gate applies again. CI green on the exact head remains required.
- Confirmed at: 2026-09-30

### QD8: QU3 local check uses a real parser; budget extension

- Status: CONFIRMED
- User answer (2026-10-01): "진짜 파서로 교체 (권장)" to the QU3 budget-exhaustion packet (cycle 5: three LOW findings, all in the hand-written YAML checker of the frontend test; the scenario file itself never had a finding).
- Normalized value: replace the hand-written checker with real parsing and schema validation using two dev dependencies (a YAML parser and a JSON Schema validator) in preview-example-frontend; QU3 review cycle budget raised from 5 to 7; the 2-of-2 clean gate is unchanged.
- Confirmed at: 2026-10-01

### QD9: QU2 review budget extension

- Status: CONFIRMED
- User answer (2026-10-01): "예산 2회차 연장 (권장)" to the QU2 budget-exhaustion packet (cycle 5: reviewer-1 clean, reviewer-2 one MEDIUM finding — GitHub scenario source uses a different YAML loader than the file source).
- Normalized value: QU2 review cycle budget raised from 5 to 7 (QU2 only); the 2-of-2 clean gate is unchanged.
- Confirmed at: 2026-10-01

### QD10: QU2 merge gate exception (low findings tolerated once)

- Status: CONFIRMED
- User answer (2026-10-01): "1건 고치고 낮은 등급은 허용 (권장)" to the second QU2 budget-exhaustion packet (cycle 7: reviewer-2 clean, reviewer-1 one LOW finding).
- Normalized value: for QU2 only — fix the finding, run one more review cycle (cycle 8); merge if neither reviewer reports a HIGH or MEDIUM finding and CI is green on the exact head; new LOW findings become required QU4 work items.
- Confirmed at: 2026-10-01

## Open questions

- None blocking the brief. Design inputs: default agent CLI (Claude Code vs Codex) and how Playwright MCP is launched and sandboxed; where reports and evidence are stored; how the scenario file is read at the pinned commit.

## Progress and evidence

- 2026-09-30: Planning started after preview-hub S4 completion. Decisions QD1–QD4 recorded. Awaiting Delivery Brief confirmation.
- 2026-09-30: Delivery Brief confirmed by the user ("응 이 범위로 확정하고 설계 시작해줘"): Q1–Q3 scope, B1–B7, STANDARD design, autonomous execution. Next: feature-design.
- 2026-09-30: Design produced (STANDARD). Spike proved claude -p + Playwright MCP headless (25.6 s, 8 turns, JSON verdict). validate_design valid; DBML parsed (3 logical tables); PlantUML not rendered (no renderer). Checklist review KR-1..5 (4 accepted, 1 rejected). Awaiting Design Gate for digest 82f3bbc855fc62e1d36e71f44bb811c7a0db7fe8a23c12d349161abd15a22d4e.
- 2026-09-30: Design Gate approved by the user for digest 82f3bbc855fc62e1d36e71f44bb811c7a0db7fe8a23c12d349161abd15a22d4e (revalidated unchanged). Next: Q1 sprint manifest.
- 2026-09-30: Q1 manifest 20260930-q1-v1 confirmed (digest 1ee14a4e4c63a6854f0b28575dfb90daece1d565b4b5387951932e11bebc9090); repository cafitac/ai-qa created (public, bootstrap ccaa70d77852aadddf59b7f759ad42c21a88a14e); SPRINT_RUNNING; QU1 and QU3 claimed.
- 2026-09-30: QU1 review budget exhausted at cycle 5 (3 findings); user extended QU1 to 7 cycles (QD5).
- 2026-09-30: QU1 review budget exhausted at cycle 7 (4 low findings); user extended QU1 to 9 cycles (QD6).
- 2026-09-30: QU1 review budget exhausted at cycle 9 (3 low findings); user granted the QU1-only merge exception QD7.
- 2026-10-01: QU1 merged (184afab9) under QD7 after cycle 10 (no HIGH/MEDIUM); four low findings carried into QU2. QU2 reserved and claimed.
- 2026-10-01: QU3 review budget exhausted at cycle 5; user chose real parser + 2 more cycles (QD8).
- 2026-10-01: QU3 merged (preview-example-frontend 8d977155) after review cycle 6 clean 2/2 (QD8).
- 2026-10-01: QU2 review budget exhausted at cycle 5 (1 medium finding); user extended QU2 to 7 cycles (QD9).
- 2026-10-01: QU2 budget exhausted at cycle 7 (1 low); user granted the QU2-only low-findings exception QD10.
- 2026-10-01: QU2 merged (0ee478ac) after review cycle 8 clean 2/2. QU4 reserved and claimed; owner login requested.
- 2026-10-02: QU4 merged (62782339) after live run 1 passing B1–B5 and review cycle 3 clean 2/2. SPRINT_COMPLETE for 20260930-q1-v1.
