# Context map

```mermaid
flowchart LR
    OWNER["소유자 (MacBook)"] -->|"aiqa login / aiqa run <env>"| AIQA
    subgraph MB["MacBook"]
        AIQA["ai-qa 실행기 (제안)<br/>실행 수명주기 · 상한 · 판정 검증 · 보고서"]
        AGENT["에이전트 CLI (구독)<br/>Claude Code 기본 / Codex"]
        PW["Playwright MCP + 브라우저<br/>시나리오마다 격리된 컨텍스트"]
        RUNS["실행 폴더 runs/<id>/<br/>report.json · 증거"]
        STATE["Access 세션 파일<br/>저장소 밖 · 0600"]
    end
    AIQA -->|"시나리오 1개 = 호출 1회"| AGENT --> PW
    AIQA --> RUNS
    AIQA -. "경로만 전달" .-> STATE
    PW -. "세션 사용" .-> STATE
    AIQA -->|"환경 설명서(descriptor) 조회"| HUB["preview-hub 대시보드 API<br/>(현재)"]
    AIQA -->|"고정 커밋의 qa/scenarios.yaml"| GH["GitHub (공개 저장소)"]
    PW -->|"허용된 주소만"| ENV["Preview 환경<br/>phub-<env>.cafitac.com"]
    ACCESS["Cloudflare Access"] --- HUB
    ACCESS --- ENV
```

- Authority: preview-hub owns environments and the descriptor; service repositories own scenarios; ai-qa owns the run (what was executed, verdict acceptance, report). The agent CLI is a tool with no authority: its answer is input that the runner validates.
- ai-qa is downstream of preview-hub and never mutates environments.
- Genuine external boundaries: `DescriptorSource` (hub API or file), `ScenarioSource` (GitHub raw or file), `AgentRunner` (Claude Code / Codex subprocess), `BrowserSession` (Playwright for login and preflight). Nothing else is abstracted.
- Q3 adds a trigger (PR comment via preview-hub's bot) and a VM container; the run core is unchanged.
