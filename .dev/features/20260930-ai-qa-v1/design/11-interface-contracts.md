# Interface contracts (ai-qa v1)

Files carry `apiVersion: ai-qa/v1`; unknown keys are rejected. JSON Schemas ship in the repository under `schemas/`.

## K1. Scenario file — `qa/scenarios.yaml` in a service repository

```yaml
apiVersion: ai-qa/v1
scenarios:
  - id: add-note                 # ^[a-z][a-z0-9-]{1,40}$, unique within the file
    title: 메모를 추가하면 목록 맨 위에 보인다
    start: /                     # path on the environment entry URL (default "/")
    steps:
      - "New note 입력칸에 고유한 문장을 입력한다"
      - "Add note 버튼을 누른다"
    expect:
      - "방금 입력한 문장이 Notes 목록의 첫 번째 항목으로 보인다"
    tags: [smoke]
    timeout: 300s                # optional, <= run cap
```

- Scenario ids are reported as `<service>/<id>`.
- Scenario text is data: it is fenced inside the prompt and can never change tools, origins, caps or output format.
- Limits: at most 50 scenarios per file, 20 steps and 10 expectations per scenario, 500 characters per line.

## K2. CLI

```
aiqa login                       # headed browser; owner signs in to Access; saves the session
aiqa run <env> [--tag T ...] [--only service/id ...] [--descriptor FILE] [--scenarios FILE] [--agent claude|codex]
aiqa show [<run-id>]             # summary of a run (latest by default); marks stale RUNNING as INTERRUPTED
aiqa doctor                      # checks agent CLI, npx, Playwright browsers, session presence (never prints secrets)
```
Exit codes: 0 all PASSED (SKIPPED allowed), 1 at least one FAILED, 2 invalid input, 3 refused (login required, environment not ready, no scenarios), 4 aborted/interrupted.

## K3. Agent contract (one call per scenario)

Invocation (Claude Code; Codex maps the same fields):
`claude -p <prompt> --output-format stream-json --verbose --max-turns <cap> --mcp-config <file> --strict-mcp-config --allowedTools <browser tool list> --disallowedTools <everything else>` in an empty temporary working directory, stdin closed, its own process group, killed at the wall-clock timeout.

Allowed browser tools: navigate, navigate_back, snapshot, click, type, press_key, select_option, hover, wait_for, take_screenshot. Not allowed: evaluate/run_code, file upload, network mocking, tabs to arbitrary URLs, any non-Playwright tool.

Prompt structure (fixed by the runner): role and rules → allowed start URL → the scenario fenced as data → required procedure (open start URL, perform steps, check every expectation, take a final screenshot named `final.png`) → required final answer.

Required final answer: exactly one JSON object
```json
{"status": "PASSED|FAILED", "summary": "<= 500 chars", "checks": [{"expect": "…", "ok": true, "observed": "…"}]}
```
PASSED only if every expectation was observed. Anything else (no JSON, extra prose, unknown status) is `agent_protocol`; one retry, then FAILED.

Transcript: the stream-json lines are stored as `agent.jsonl`; the runner extracts every `browser_navigate` URL and the turn count from it.

## K4. Browser session and allow-list

- Session file: `~/.config/aiqa/access-state.json` (Playwright storage state, mode 0600, directory 0700). Created by `aiqa login`; refused if the Access cookie is not HttpOnly. Never copied into the run directory or the prompt.
- Per run the preflight writes a temporary state file (0600, deleted at the end) that also holds the environment-host cookie; Playwright MCP receives it with `--isolated --storage-state <path>`.
- Allowed origins = every origin in the descriptor (entry URL and service public URLs) + the Access team origin (needed for the cross-host redirect). Passed to Playwright MCP as `--allowed-origins`; enforced for the report by the transcript check (any navigation outside → scenario FAILED `out_of_scope`).
- Redaction: before a scenario result is recorded, every file in its directory is scanned for the session cookie values, `CF_Authorization`, `eyJ…` JWT shapes and `gh[pousr]_` tokens; a hit deletes the offending file, records `log` evidence "redacted" and fails the scenario with `agent_error`.

## K5. Run directory and report mapping

```
runs/<run-id>/
  run.json          # ai-qa/v1 Run: id, environment, commits, state, budget, agent, started/finished, results
  report.json       # qa-report/v1 (preview-hub schema), written only at COMPLETED
  summary.md        # human-readable table
  scenarios/<service>__<id>/
    result.json     # ScenarioResult
    agent.jsonl     # transcript
    final.png, *.png, page-*.yml   # Playwright MCP output
```
Mapping to `qa-report/v1`: `environment` = descriptor name; `commits` = descriptor services; `scenarios[].id` = `<service>/<id>`; `status` as is; `summary` = agent summary or gate reason; `evidence` = screenshot files (`type: screenshot`) and `agent.jsonl` (`type: log`), `uri` relative to the run directory; `summary` counts. A REFUSED or ABORTED run writes no `report.json`.

## K6. Configuration — `aiqa.yaml` (optional, working directory or `--config`)

```yaml
apiVersion: ai-qa/v1
hub:
  dashboard_url: https://preview-hub.cafitac.com
  access_team_domain: cafitac.cloudflareaccess.com
agent:
  kind: claude            # claude | codex
  model: null             # CLI default unless set
budget:
  max_scenarios: 20
  max_turns: 25
  scenario_timeout: 300s
  protocol_retries: 1
runs_dir: ./runs
playwright_mcp: "@playwright/mcp@<pinned>"
```
Environment overrides: `AIQA_CONFIG`, `AIQA_RUNS_DIR`, `AIQA_STATE_FILE`.
