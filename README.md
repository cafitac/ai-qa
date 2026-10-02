# ai-qa

MIT-licensed, local scenario-runner core (Python 3.12, uv). Claude Code drives a bounded Playwright MCP session. Codex is **experimental**, unit-tested for invocation and parsing only; live compatibility and tool isolation are not yet proven. Fake results are development fixtures, not QA evidence.

## Install

Install Python 3.12+, uv, Node.js/npx, and the Claude Code subscription CLI, then:

```sh
uv sync
uv run playwright install chromium
```

The default Playwright MCP version is pinned (`@playwright/mcp@0.0.83`); any
configured override must also be an exact version.

## Login

The owner runs `uv run aiqa login`, signs in to Cloudflare Access in the headed
browser, then runs `uv run aiqa doctor`. Login requires HttpOnly Access cookies
and saves `~/.config/aiqa/access-state.json` with mode 0600. Doctor checks session
presence and permissions; run preflight checks whether it still works. Never
copy session contents into scenario files or run directories. Only exact-host cookies (including Access cookies) and
localStorage for the dashboard host, Access team domain, and `phub-*` environment
hosts are stored; parent-domain cookies such as `.cafitac.com` and GitHub SSO
cookies are not kept. The environment zone is set by
`hub.environment_domain` (default `cafitac.com`). Re-run `aiqa login` when the
Access session expires.

## Writing scenarios

K1 files live at `qa/scenarios.yaml` in each public service repository. The
example frontend uses `frontend/seed-notes-listed` and
`frontend/add-note-shows-first`:

```yaml
apiVersion: ai-qa/v1
scenarios:
  - id: seed-notes-listed
    title: Seed notes are listed
    start: /
    steps:
      - Open the Notes page and inspect the list
    expect:
      - The seeded notes appear in the Notes list
    tags: [smoke]
  - id: add-note-shows-first
    title: Adding a note shows it first
    steps:
      - Enter a unique sentence in the New note input
      - Click Add note
    expect:
      - The new sentence is the first item in the Notes list
```

IDs are unique per file and match `^[a-z][a-z0-9-]{1,40}$`. Limits are 50
scenarios per file, 20 steps, 10 expectations, and 500 characters per text line.
An optional `timeout: 300s` must not exceed the run timeout cap. Scenario text
is fenced data and cannot change tools, origins, budgets, or output format.

## Running

```sh
uv run aiqa run demo
uv run aiqa run demo --only frontend/seed-notes-listed
uv run aiqa run demo --tag smoke
uv run aiqa show
# Offline development fixtures:
uv run aiqa run demo --descriptor descriptor.json --scenarios scenarios.yaml --agent fake
```

`--agent fake` is development-only and must be explicitly selected. Scenario files use `apiVersion: ai-qa/v1` and the K1 schema in `schemas/`. For multiple services, `--scenarios` takes a directory containing `<service>.yaml` files; missing files mean no scenarios for that service. Every scenario `start` (default `/`) is an absolute path on the environment `entryUrl` origin (the path prefix of `entryUrl` is not applied), including scenarios from other services; all scenarios start on the entry origin. `--tag` and `--only service/id` may be repeated.

Optional `aiqa.yaml` / `--config FILE` configures budgets and output paths. `AIQA_CONFIG`, `AIQA_RUNS_DIR`, and `AIQA_STATE_FILE` override their respective paths (explicit `--config` wins); empty or whitespace-only overrides are treated as unset. Defaults: 20 scenarios, 25 turns, 300 seconds, one protocol retry **per run**. The runner passes caps to adapters and rejects reported cap violations; CLI processes and their browser children are terminated as a process group at the wall-clock timeout. Scenario duration ends when the process wait completes or times out; cleanup time is excluded, and the wait timeout flag determines timeout.

## Reading a report

Runs are stored in `runs/<environment>-<UTC timestamp>/`: atomic `run.json`, per-scenario `result.json`, transcripts, `summary.md`, and a schema-validated preview-hub report on completion only. Existing run ids are refused. `show` views a CREATED, PREFLIGHT, or RUNNING run with a dead pid as INTERRUPTED without rewriting history. A COMPLETED run without a valid `report.json` is shown in progress (exit 5) only while another runner process is live, and INTERRUPTED (exit 4) otherwise. Recovery computes the terminal view without PID liveness, so failed recovery writes never label the finished runner RUNNING.

K2 exit codes: 0 no failed scenarios (skips allowed), 1 failed scenario, 2 invalid input/unavailable adapter, 3 refused preflight, 4 aborted/interrupted, 5 run still in progress. `show` returns the same exit code represented by the run, including failed completed runs and refused preflight reasons. Infrastructure/storage errors return 4. No resume.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Preflight input reasons: `invalid_descriptor` for descriptor file, schema, or URL errors; `invalid_scenarios` for scenario input errors (exit 2).

Preflight refuses expired descriptors (`expiresAt` at or before the current time) as `environment_not_ready` before any agent call. Aborted runs record only the exception class as `abort_reason` (`interrupted` for Ctrl-C), never the exception message. Each agent call writes to its own runner-created `scenarios/<service>__<id>/attempt-<n>/` directory; `result.json` sits beside these directories. Every entry in the current attempt is passed to the gate, including agent-created `attempt-1` names. Earlier attempts remain for audit and are excluded from retry evidence. File evidence (`screenshot`, `log`) must be an existing regular file in the current attempt (subdirectories allowed; symlinks are never followed and never count as evidence); URIs are relative to the run directory. HTTP evidence keeps its HTTP/HTTPS URL and must use an allowed origin. Symlinks in attempt directories are ignored by collection and the regular-file-only redaction scan, without a redaction hit. Gate evidence pointing to a symlink or outside the current attempt is invalid. Invalid gate evidence fails the scenario as `agent_protocol`. Filesystem errors handling agent output fail only that scenario as `agent_error`; runner artifact write failures abort the run.

Malformed agent verdicts fail only their scenario as `agent_protocol`, using at most one shared retry per run. Persisted agent summary and check text must be valid UTF-8, at most 500 characters per value, and contain no control characters except newline and tab. File/schema input errors return exit 2 without a traceback. The injected clock governs descriptor expiry, run IDs, and all run/report timestamps.

## Limits and safety

Configure `playwright_mcp` with an exact version (`@playwright/mcp@x.y.z`), install
Chromium with `uv run playwright install chromium`, then run `aiqa doctor` and
`aiqa login`. Login opens a headed browser for the owner and requires HttpOnly
Access cookies and saves the session with private permissions. `aiqa run demo --agent claude` reads the
hub descriptor and scenario files at their pinned GitHub commits. `--descriptor`
and `--scenarios` override those sources independently. No session contents are
printed; temporary browser state is deleted on completion or abort. Redaction covers Access cookie values (including cookies on the configured
Access team domain), Access cookie names (`CF_Authorization`, `CF_AppSession`,
`CF_Binding`), JWT shapes, `gh[pousr]_` GitHub token shapes and `github_pat_`.
It scans attempt files and parsed verdict text before persistence; a hit deletes
the offending artifact and fails the scenario as `agent_error`. This is not a
general scrubber for arbitrary passwords or personal data. Use synthetic data.

Playwright MCP writes snapshots to the attempt directory via `--output-dir`, but relative screenshots such as `final.png` may land in the agent’s initially empty temporary working directory. After stopping the agent and its children, the runner collects up to 20 PNG/JPEG files (at most 10 MiB each, matching image magic bytes) from that directory and one level of subdirectories before deleting it, including on timeout. Symlinks, invalid evidence URI names, and existing destination files are skipped. Collected images pass through the same redaction and verdict gate as other attempt files.

Scenario retrieval supports **public repositories only**. A missing scenario file is skipped only after GitHub confirms the pinned commit is publicly readable; the summary reports "no scenario file". A GitHub visibility 404 refuses as `invalid_scenarios` (exit 2). Visibility 403/429 with `X-RateLimit-Remaining: 0` or `Retry-After` refuses as `source_unavailable` with "GitHub rate limit; retry later" (exit 3); other HTTP failures and network errors abort at the source boundary (exit 4).

Claude isolation (K3): `--tools ""` disables every built-in tool; `--restricted`, `--strict-mcp-config`, `--setting-sources ""`, `--permission-prompts none`, and `--no-session-persistence` isolate settings, MCP configuration, permission prompts, and session history. `--allowedTools` contains exactly the ten Playwright tools: navigate, navigate_back, snapshot, click, type, press_key, select_option, hover, wait_for, take_screenshot. The empty setting-source value is a documented constant for CLI 2.1.285; if a CLI version rejects it, omit that flag because restricted mode already ignores settings files. `--bare` is intentionally absent to preserve keychain-backed subscription login.

Scenario data is sent as UTF-8 JSON inside an escaped fence. K3 agent checks use zero-based indexes (`{"index": 0, "ok": true, "observed": "..."}`), with every expectation index present exactly once. Duplicate, missing, non-integer, or out-of-range indexes fail as `agent_protocol`. Stored checks retain the original scenario expectation text. Playwright errors during login or doctor return exit 4 with a one-line message; closing the login browser reports `login cancelled`.

## Live check (e2e/live.sh)

The owner must already have run `uv run aiqa login`. From this checkout:

```sh
PREVIEW_HUB_DIR="$HOME/Project/cafitac/preview-hub" \
  PHUB_SSH_OPTS="-o BatchMode=yes" AIQA_CALL_CAP=30 sh e2e/live.sh
```

This MacBook script checks doctor, refuses a missing environment (B3), creates
main and broken-backend environments (B1/B2), validates reports, final screenshots
and commits, scans run artifacts for token shapes (B4), and reruns only the smoke
scenario with a one-turn budget (B5). It requires the public example scenario file
and the backend `e2e-broken-add-note` branch. The runner rejects reported TURN cap
violations; timeout is decided by the process wait timeout, excluding cleanup.

The script pins Claude in both the command and generated configs, preserving the
owner’s hub (including environment domain), model, MCP and runs directory settings.
It clamps scenarios to min(owner, 2), shared protocol retries to min(owner, 1),
normal-run turns to min(owner, 25), and normal-run timeout to min(owner, 300 s).
The capped run uses one turn. Before each run it checks the call cap against a
reservation of clamped scenarios + retries, or 1 + retries for the `--only` run.
It counts direct scenario attempt directories as calls. `AIQA_CALL_CAP` defaults
to 30 and covers this invocation; the operator must also respect the sprint-wide
remaining allowance. It never prints command output containing agent text or
credentials. A trap deletes both test environments and asserts empty inventories;
cleanup failure is an error requiring the owner to retry. Evidence remains under
the configured runs directory, including on failure. The script creates/deletes preview environments
and makes real subscription agent calls; unit tests do neither.
