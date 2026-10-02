# Design index

- Feature record: ../feature.md
- Feature ID: 20260930-ai-qa-v1
- Current slice: Q1 MacBook runner (contracts also cover Q2/Q3 boundaries coarsely)
- Current PR unit: pending (derived by feature-plan from this design)
- Design profile: STANDARD
- Design status: AWAITING_APPROVAL
- Target/base: main (new personal repository cafitac/ai-qa)

## Source evidence

- Greenfield: no ai-qa code exists. No Earlypay code, configuration or rules are used.
- preview-hub (main 8eed847) provides: `environment-descriptor/v1` (schemas/environment-descriptor.schema.json; `GET /api/environments/{name}?format=descriptor` behind Access, or `phub status <env> --format descriptor`), `qa-report/v1` (schemas/qa-report.schema.json: environment, commits, startedAt, finishedAt, scenarios[{id,status PASSED|FAILED|SKIPPED,summary,evidence[{type screenshot|log|http,uri}]}], summary counts), one origin per environment `https://phub-<env>.cafitac.com` with services under `/_svc/<sub>`, Cloudflare Access (GitHub SSO + one-time PIN) in front of every public host, and hub-side JWT verification that requires an `email` claim (so Access service tokens do not pass today — Q3 concern).
- Example frontend: React app "Preview notes" (list of notes, textarea "New note", button "Add note"), API at `${apiUrl}/api/notes`; public example repositories.
- Tools on the MacBook (2026-09-30): Claude Code CLI 2.1.285 and Codex CLI on subscription logins; Node/npx; `@playwright/mcp` options verified from `--help`: `--headless`, `--isolated`, `--storage-state`, `--allowed-origins`, `--blocked-origins`, `--output-dir`, `--console-level`, timeouts.
- Spike (2026-09-30, scratch directory, not product code): `claude -p ... --mcp-config <playwright> --strict-mcp-config --allowedTools mcp__playwright__browser_navigate,browser_snapshot,browser_take_screenshot --max-turns 8 --output-format json` ran headless against https://example.com in 25.6 s, 8 turns, returned the requested JSON verdict in `result`, and wrote a page snapshot into `--output-dir`; tools outside the allow-list (`browser_evaluate`) were denied. Observations used below: the turn cap is consumed quickly (8 turns for one page), screenshots need an explicit file name, and the result JSON reports `num_turns`/`duration_ms`.

## Artifact ledger

| Artifact | Status | Evidence / reason |
|---|---|---|
| Context map | REQUIRED | ai-qa, preview-hub, agent CLI, browser, GitHub and Cloudflare Access are separate authorities. |
| Domain model | REQUIRED | Run aggregate, scenario/verdict/evidence values and the AgentRunner, BrowserSession, DescriptorSource, ScenarioSource boundaries. |
| Current schema | N/A | Greenfield: nothing to observe. |
| Target schema | REQUIRED | No database engine: `04-target-schema.dbml` records the logical model of the run directory (JSON files written atomically by one process); the physical layout is `11-interface-contracts.md` K5 and the public report schema is owned by preview-hub. |
| Transaction flows | REQUIRED | Login, run (preflight → per-scenario agent call → report) and failure paths. |
| State machines | REQUIRED | Run and scenario states drive refusal, timeout, partial results and interruption. |
| Consistency and migration | REQUIRED | Atomic file writes, process cleanup, session handling, budgets, redaction. |
| Acceptance trace | REQUIRED | Maps B1–B7. |
| Visual review pack | REQUIRED | User-facing review in Korean. |

Supplementary (part of the reviewed set): `01-context-map.md`, `06-state-machines.puml`, `11-interface-contracts.md` (K1 scenario file, K2 CLI, K3 agent contract, K4 browser session and allow-list, K5 run directory and report mapping, K6 configuration).

## Confirmed decisions

- QD1 AI drives the browser directly through Playwright; driver behind an interface; Aside not built.
- QD2 Repository-authored natural-language scenarios always run; AI proposals from PR diffs are suggestions only (Q2).
- QD3 MacBook first (Q1), then VM container (Q3).
- QD4 STANDARD design, autonomous sprint, two Claude reviewers, agent merges cafitac PRs after gates.

## Proposed decisions

- KP1 One agent call per scenario: `claude -p` (default) or `codex exec` as a subprocess in an empty temporary working directory, with only Playwright browser tools allowed (no shell, file or web tools), `--strict-mcp-config`, a turn cap and a wall-clock timeout. One scenario = one fresh isolated browser context, so scenarios cannot contaminate each other.
- KP2 The verdict is the agent's, but the runner does not trust it blindly: a result is accepted only if the final message is the required JSON object, at least one screenshot file exists for a PASSED verdict, every navigation in the transcript stayed inside the allowed origins, and the caps were respected; otherwise the scenario is FAILED with a machine reason (`agent_protocol`, `no_evidence`, `out_of_scope`, `timeout`, `turn_cap`, `agent_error`).
- KP3 Access in Q1 = a browser session the owner creates once with `aiqa login` (headed Playwright window → GitHub SSO); the storage state file is kept outside the repository with mode 0600 and is never shown to the agent as text. Each run starts with a runner-side preflight (headless, same state) that must land on the environment origin; an expired session stops the run with "run aiqa login" before any agent call.
- KP4 The descriptor is fetched from the dashboard API through that same browser session (`GET https://preview-hub.cafitac.com/api/environments/<env>?format=descriptor`); `--descriptor <file>` is the offline alternative. No SSH or Docker access is needed by ai-qa.
- KP5 Scenario files are read from `https://raw.githubusercontent.com/<repo>/<commit>/qa/scenarios.yaml` for every service in the descriptor (public repositories, no credential); a service without the file contributes no scenarios; `--scenarios <file>` overrides for local authoring.
- KP6 Storage is a run directory per run (`runs/<run-id>/`), written atomically (temp file + rename); no database. `report.json` is `qa-report/v1`; `run.json` holds ai-qa's own richer state.
- KP7 Budgets are counted in agent calls, turns and seconds (not money): defaults 25 turns and 300 s per scenario, 20 scenarios and one protocol retry per run; all configurable downward or upward in `aiqa.yaml`.
- KP8 Python 3.12 + uv; dependencies: PyYAML, jsonschema, playwright (Python, for login/preflight/descriptor fetch). Playwright MCP is launched by the agent CLI through `npx @playwright/mcp@<pinned version>`.
- KP9 Default agent is Claude Code because the spike proved the exact headless contract; Codex is a second implementation of the same AgentRunner interface, proven before it is documented as supported.

## Open questions

- KO1 (Q3, not blocking Q1) Service identity for unattended runs: Access service token + preview-hub accepting non-email identities, and a long-lived agent CLI token in the VM.
- KO2 (SAFE_ASSUMPTION) `--allowed-origins` is documented as a convenience filter, not a security boundary; the transcript check in KP2 is the enforcing layer for the report, and the example services hold only synthetic data.

## Review findings

- Checklist pass (no independent agent review; STANDARD profile):
  - KR-1 (accepted, KP2): an agent could report PASSED without doing anything → evidence, transcript and cap checks gate acceptance.
  - KR-2 (accepted, KP3/K4): the Access cookie must not reach the model → browser tools only (no evaluate, no file tools), storage state passed by path, redaction scan of every written artifact, HttpOnly cookie requirement checked at login.
  - KR-3 (accepted, 07): orphan browser/agent processes after Ctrl-C or a crash → process-group kill on exit and stale-run detection.
  - KR-4 (accepted, K1): scenarios are repository content and therefore prompt input → treated as data: fixed system instructions, scenario text fenced, allowed tools and origins fixed by the runner, never by scenario text.
  - KR-5 (rejected): SQLite run ledger — a single writer and append-only directories need no database.

## Validation evidence

- `validate_design.py --record ../feature.md`: see the feature record for the result and digest.
- PlantUML renderer not installed; `02`, `05`, `06` are mirrored in the Mermaid review pack. `npx -p @dbml/cli dbml2sql 04-target-schema.dbml --postgres` parses the logical file model (3 tables).
