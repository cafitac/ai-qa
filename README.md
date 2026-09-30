# ai-qa

MIT-licensed, local scenario-runner core (Python 3.12, uv). QU1 has **no real agent or browser integration yet**. Claude and Codex return “not available yet” with exit 2. The JSON verdict gate is a placeholder; fake PASSED results are not QA evidence.

```sh
uv sync
uv run aiqa run demo --descriptor descriptor.json --scenarios scenarios.yaml --agent fake
uv run aiqa show
```

`--agent fake` is development-only and must be explicitly selected. Scenario files use `apiVersion: ai-qa/v1` and the K1 schema in `schemas/`. For multiple services, `--scenarios` takes a directory containing `<service>.yaml` files; missing files mean no scenarios for that service. Every scenario `start` (default `/`) is an absolute path on the environment `entryUrl` origin (the path prefix of `entryUrl` is not applied), including scenarios from other services; all scenarios start on the entry origin. `--tag` and `--only service/id` may be repeated.

Optional `aiqa.yaml` / `--config FILE` configures budgets and output paths. `AIQA_CONFIG`, `AIQA_RUNS_DIR`, and `AIQA_STATE_FILE` override their respective paths (explicit `--config` wins); empty or whitespace-only overrides are treated as unset. Defaults: 20 scenarios, 25 turns, 300 seconds, one protocol retry **per run**. The runner passes caps to adapters and rejects reported cap violations; real process timeout enforcement belongs to QU2.

Runs are stored in `runs/<environment>-<UTC timestamp>/`: atomic `run.json`, per-scenario `result.json`, transcripts, `summary.md`, and a schema-validated preview-hub report on completion only. Existing run ids are refused. `show` views a CREATED, PREFLIGHT, or RUNNING run with a dead pid as INTERRUPTED without rewriting history. A COMPLETED run without a valid `report.json` is also viewed as INTERRUPTED (exit 4).

K2 exit codes: 0 no failed scenarios (skips allowed), 1 failed scenario, 2 invalid input/unavailable adapter, 3 refused preflight, 4 aborted/interrupted, 5 run still in progress. `show` returns the same exit code represented by the run, including failed completed runs and refused preflight reasons. Infrastructure/storage errors return 4. No resume.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
```

Preflight input reasons: `invalid_descriptor` for descriptor file, schema, or URL errors; `invalid_scenarios` for scenario input errors (exit 2).

Preflight refuses expired descriptors (`expiresAt` at or before the current time) as `environment_not_ready` before any agent call. Aborted runs record only the exception class as `abort_reason` (`interrupted` for Ctrl-C), never the exception message. Each agent call writes to its own runner-created `scenarios/<service>__<id>/attempt-<n>/` directory; `result.json` sits beside these directories. Every entry in the current attempt is passed to the gate, including agent-created `attempt-1` names. Earlier attempts remain for audit and are excluded from retry evidence. File evidence (`screenshot`, `log`) must be an existing regular file in the current attempt (subdirectories allowed; symlinks must not escape it); URIs are relative to the run directory. HTTP evidence keeps its HTTP/HTTPS URL and must use an allowed origin. Invalid gate evidence fails the scenario as `agent_protocol`. Filesystem errors handling agent output fail only that scenario as `agent_error`; runner artifact write failures abort the run.

Malformed agent verdicts fail only their scenario as `agent_protocol`, using at most one shared retry per run. Persisted agent summary and check text must be valid UTF-8, at most 500 characters per value, and contain no control characters except newline and tab. File/schema input errors return exit 2 without a traceback. The injected clock governs descriptor expiry, run IDs, and all run/report timestamps.
