# Consistency and migration

## Transaction and aggregate boundaries

- Aggregate: `Run` = `run.json` plus its scenario result files. One process writes one run directory; every write is temp-file + `os.replace` (atomic on the same filesystem), so a reader never sees a half-written file.
- No database and no cross-run state. `report.json` is derived from `run.json` and written once at COMPLETED after schema validation.

## Identity, idempotency, and result-unknown recovery

- Run id `<env>-<UTC yyyymmddThhmmssZ>`; a collision (same second) is refused. Runs are append-only history; re-running creates a new run.
- Scenario identity `<service>/<id>`; duplicate ids within a file are an invalid-input refusal before any agent call.
- Result unknown: if the runner dies, `run.json` stays RUNNING with its pid; `aiqa show` reports it as INTERRUPTED when the pid is gone. Scenario results already written stay valid; no resume.

## Isolation, locks, and retry ownership

- Scenarios run sequentially; each agent call gets a fresh isolated browser context and its own temporary working directory and output directory.
- Child processes (agent CLI, MCP server, browser) are started in one process group per scenario and terminated (TERM, then KILL after 5 s) on timeout, completion, Ctrl-C or any runner exception.
- Retry: exactly one retry for `agent_protocol`; no retry for verdict FAILED, timeout or turn cap (the owner re-runs). The runner never retries to turn a FAILED into a PASSED.

## External effects and consistency protocol

- preview-hub: read-only (descriptor). GitHub: read-only raw scenario files at the pinned commit. The environment under test: whatever the scenarios do through the browser (example services use synthetic data; scenarios should create uniquely named data).
- Agent CLI: subscription usage, bounded by the budget (calls, turns, seconds). No metered API, no paid service.
- Access session: created only by the owner in a headed window; ai-qa stores the Playwright state file locally (0600), passes its path to the browser tooling, deletes per-run temporary copies, and never prints or reports cookie values (redaction scan as the last gate).

## Failure and recovery owners

| Effect | Starts | Observes | Reconciles / retries | Cleans up | Verifies |
|---|---|---|---|---|---|
| Run directory | RunScenarios | `aiqa show` | none (append-only) | owner deletes old runs | B1 |
| Agent + browser processes | AgentRunner | runner (timeout, exit) | one protocol retry | process-group kill | B5 tests |
| Temporary storage state | preflight | runner | none | deleted at run end / abort | B4 |
| Access session file | `aiqa login` | preflight | owner re-login | owner (`aiqa login` overwrites) | B3 |
| Data created in the environment | scenarios | report | none | environment is disposable (`phub down`) | n/a |

## Capacity and safety limits

- Defaults: 20 scenarios per run, 25 turns and 300 s per scenario, one protocol retry per run → at most 21 agent calls and about 100 minutes; all lower in practice (the spike used 8 turns / 26 s for one page).
- Prompt injection from scenario text or page content cannot widen authority: tools, origins, caps and output format are fixed by the runner; the working directory is empty; no shell or file tools exist for the agent.

## Current-to-target migration

- Compatibility and deploy order: greenfield repository; local CLI installed with `uv tool install` or run with `uv run`; no deployment in Q1.
- Backfill and verification: none.
- Rollback: delete the checkout and `~/.config/aiqa`.
- Shadow / cutover / kill switch: not applicable.

## Access paths and index evidence

- None (no database). `aiqa show` lists `runs/*/run.json` sorted by name.

## Audit, privacy, and retention

- The run directory is the audit record: who (local user), when, environment, commits, agent kind/model, per-scenario transcript and evidence. Retention is the owner's (`runs/` is git-ignored).
- Screenshots and transcripts may show application data; the example services are synthetic. Secrets are excluded by design and by the redaction scan.
