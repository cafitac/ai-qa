from __future__ import annotations

import json
from pathlib import Path

from ..contracts import Scenario
from ..ports import AgentContext
from .claude import TOOLS, ClaudeCodeRunner, mcp_args, prompt


class CodexRunner(ClaudeCodeRunner):
    """Experimental Codex CLI adapter; no live compatibility claim."""

    def command(
        self, scenario: Scenario, context: AgentContext, mcp: Path
    ) -> list[str]:
        args = mcp_args(self.config, context)
        command = [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "-c",
            'mcp_servers={playwright={command="npx",args='
            + json.dumps(args)
            + ",enabled_tools="
            + json.dumps([tool.removeprefix("mcp__playwright__") for tool in TOOLS])
            + "}}",
            "-c",
            'approval_policy="never"',
            "-c",
            "features.shell_tool=false",
            "-c",
            "features.apply_patch_freeform=false",
            "-c",
            'web_search="disabled"',
        ]
        if context.model:
            command += ["--model", context.model]
        return [*command, prompt(scenario, context)]
