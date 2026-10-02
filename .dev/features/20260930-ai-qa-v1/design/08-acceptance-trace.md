# Acceptance trace

PR units are provisional; `feature-plan` fixes them in the sprint manifest (QU1 core + contracts with fakes; QU2 agent/browser adapters, login, gate, redaction; QU3 example scenarios and a deliberately broken branch in the example repositories; QU4 live E2E and README).

| Acceptance ID | Design flow / artifact | Persisted effect and invariant | Automated evidence | Runtime evidence | Rollback evidence | PR unit |
|---|---|---|---|---|---|---|
| B1 | 05 run flow; 11 K1–K5; 02 Run | run.json COMPLETED; report.json validates qa-report/v1; commits = descriptor | unit: full run with FakeAgentRunner and fake sources; report schema test | live: `aiqa run <env>` on the example environment, two scenarios PASSED, screenshots present | delete run dir | QU1, QU2, QU3, QU4 |
| B2 | 05 loop; 06 scenario FAILED; 11 K3 | result FAILED with reason and evidence; exit 1 | unit: agent FAILED verdict and gate reasons | live: environment from the broken branch → add-note FAILED, other scenario still PASSED | delete run dir | QU3, QU4 |
| B3 | 05 preflight alts; 06 REFUSED | run.json REFUSED; no agent call; no report.json | unit: not READY / unhealthy / unknown / no session / no scenarios → exit 3, zero agent calls | live: `aiqa run missing-env` | n/a | QU1, QU2 |
| B4 | 11 K4; 07 external effects; 02 VerdictGate, Redactor | out_of_scope FAILED; no secret in any written file | unit: transcript with an outside navigation; redaction of cookie/JWT/token patterns; session file permissions | live: grep the run directory for cookie/JWT shapes | n/a | QU2, QU4 |
| B5 | 06 timeout/turn_cap; 07 isolation and limits | FAILED(timeout/turn_cap); run continues; calls <= cap; no orphan processes | unit: fake agent that hangs / exceeds turns; process-group kill test | live: one scenario with a 1-turn cap | n/a | QU1, QU2 |
| B6 | Q2 (coarse) | proposals in the report, not executed | later | later | n/a | Q2 |
| B7 | Q3 (coarse); KO1 | one PR comment | later | later | n/a | Q3 |
