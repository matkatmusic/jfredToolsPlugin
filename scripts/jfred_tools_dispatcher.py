#!/usr/bin/env python3
"""Entry point for the jfredToolsPlugin.

Routes the UserPromptSubmit hook payload (stdin JSON) to /run-scenario and
/sync-jsonl-projects, and the argv-mode run-scenario-* subcommands (fired by
the driven agent's generated hooks) to run_scenario_lib. Prompts surfaced
under the plugin namespace (/jfredToolsPlugin:<cmd>) are normalized to the
bare command first. Unconsumed prompts exit 0 with empty stdout (silent
passthrough, so Claude Code processes the prompt normally).
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
# run_scenario_lib + bg_permissions_lib locate the plugin root and the
# permissions asset (assets/bg_agent_permissions.json) through the plugin env
# contract; Claude Code sets these for plugin hooks, manual runs get defaults.
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", str(_ROOT))
os.environ.setdefault("CLAUDE_PLUGIN_DATA", str(_ROOT / ".plugin_data"))

from external.claude_plugin_lib.util_lib import _util_matches_prefix  # noqa: E402
from common.scripts.run_scenario_lib import (  # noqa: E402
    runScenario_execute,
    runScenario_launch,
    runScenario_launchAndExecute,
    runScenario_main,
    runScenario_saveTxtAsJson,
    runScenario_sessionEnd,
    runScenario_sessionStart,
    runScenario_stop,
)
from common.scripts.sync_lib import sync_main  # noqa: E402

_NAMESPACE_PREFIX = "/jfredToolsPlugin:"

# Argv subcommand -> adapter unpacking argv into the lib function's positional
# contract (mirrors jot's orchestrator routing for the run-scenario slice).
_ARGV_DISPATCH: dict = {
    "run-scenario-launch": lambda argv: runScenario_launch(*argv),
    "run-scenario-session-start": lambda argv: runScenario_sessionStart(*argv),
    "run-scenario-stop": lambda argv: runScenario_stop(*argv),
    "run-scenario-session-end": lambda argv: runScenario_sessionEnd(*argv),
    "run-scenario-execute": lambda argv: runScenario_execute(*argv),
    "run-scenario-launch-and-execute": lambda argv: runScenario_launchAndExecute(*argv),
    "run-scenario-convert": lambda argv: print(runScenario_saveTxtAsJson(argv[0])) or 0,
}

# Prompt prefix -> stdin-mode entrypoint (each re-reads the payload itself).
_PROMPT_DISPATCH: tuple = (
    ("/run-scenario", runScenario_main),
    ("/sync-jsonl-projects", sync_main),
)


def main() -> int:
    argv = sys.argv[1:]
    if argv:
        fn = _ARGV_DISPATCH.get(argv[0])
        if fn is None:
            return 0
        rc = fn(argv[1:])
        return 0 if rc is None else int(rc)

    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    prompt = (data.get("prompt", "") if isinstance(data, dict) else "").lstrip()

    if prompt.startswith(_NAMESPACE_PREFIX):
        prompt = "/" + prompt[len(_NAMESPACE_PREFIX):]
        if isinstance(data, dict):
            data["prompt"] = prompt
            raw = json.dumps(data)

    for prefix, fn in sorted(_PROMPT_DISPATCH, key=lambda p: -len(p[0])):
        if _util_matches_prefix(prompt, prefix):
            # The entrypoint reads the hook payload from stdin itself; re-pipe it.
            sys.stdin = io.StringIO(raw)
            rc = fn()
            return 0 if rc is None else int(rc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
