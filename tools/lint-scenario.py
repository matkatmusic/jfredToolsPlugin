#!/usr/bin/env python3
"""Lint a .txt scenario file before run-all-scenarios.py / run-scenario processes it.

Parses each file with the exact function the runner uses
(runScenario_convertTxtToJson), so the linter can never disagree with the
runner about what a step means, then checks:

  1. header fields session/model/ponytail present and non-empty
  2. no 'unknown' steps (lines the runner would pause on at execution time)
  3. written step numbers match the parser's 1-based order
  4. every explicitly-targeted step names a spawned (or implicit a1) agent
  5. every agent has at least one Exit and one Record resolving to it
  6. Rewind payloads match '<N>[, code]' with N <= prior Says on the target

Prints one line per finding; exits 1 if any file has findings, 0 otherwise.

Usage: lint-scenario.py <scenario.txt> [<more.txt> ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common.scripts.run_scenario_lib import runScenario_convertTxtToJson  # noqa: E402

WRITTEN_STEP_NUMBER_RE = re.compile(r"^-\s*\[[ x]\]\s*(\d+)\.")
REWIND_PAYLOAD_RE = re.compile(r"\d+(?:,\s*\S.*)?")
HEADER_FIELDS = ("session", "model", "ponytail")
SAY_ACTIONS = ("say", "sayqueued")


def lintScenario_checkHeaderFields(parsed: dict) -> list[str]:
    findings = []
    for field_name in HEADER_FIELDS:
        if not parsed[field_name]:
            findings.append(f"header: missing or empty '{field_name}:' field")
    return findings


def lintScenario_checkUnknownSteps(parsed: dict) -> list[str]:
    findings = []
    for step in parsed["steps"]:
        if step["action"] == "unknown":
            findings.append(f"step {step['step_num']}: unparseable step line: {step['payload']}")
    return findings


def lintScenario_checkWrittenStepNumbers(text: str) -> list[str]:
    # Same body rule as the parser: everything after the first '---', else the whole file.
    parts = text.split("---", 1)
    body = parts[1] if len(parts) > 1 else parts[0]
    findings = []
    parseOrder = 0
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ["):
            continue
        parseOrder += 1
        match = WRITTEN_STEP_NUMBER_RE.match(stripped)
        if match is None:
            continue  # numberless lines already surface as 'unknown' in check 2
        writtenNumber = int(match.group(1))
        if writtenNumber == parseOrder:
            continue
        findings.append(f"step {parseOrder}: written number {writtenNumber} does not match parse order {parseOrder}")
    return findings


def lintScenario_createAgentWalkState() -> dict:
    # Mirrors runScenario_executeSteps' initial state: a1 is implicit and active.
    return {
        "agents": {"a1"},
        "active": "a1",
        "agent_index": 1,
        "says_by_agent": {"a1": 0},
        "exit_agents": set(),
        "record_agents": set(),
    }


def lintScenario_resolveStepTarget(step: dict, state: dict) -> tuple[str, str | None]:
    # Executor rule: explicit @target wins, else the currently active agent.
    explicitTarget = step["target"]
    if explicitTarget is None:
        return state["active"], None
    if explicitTarget in state["agents"]:
        return explicitTarget, None
    return explicitTarget, f"step {step['step_num']}: targets unspawned agent @{explicitTarget}"


def lintScenario_checkRewindStep(step: dict, targetName: str, state: dict) -> str | None:
    if step["action"] != "rewind":
        return None
    payload = step["payload"].strip()
    match = REWIND_PAYLOAD_RE.fullmatch(payload)
    if match is None:
        return f"step {step['step_num']}: Rewind payload '{payload}' is not of the '<N>[, code]' form"
    rewindDepth = int(payload.split(",", 1)[0])
    priorSayCount = state["says_by_agent"][targetName]
    if rewindDepth > priorSayCount:
        return f"step {step['step_num']}: Rewind {rewindDepth} exceeds {priorSayCount} prior Say(s) on @{targetName}"
    return None


def lintScenario_applySpawnToAgentState(step: dict, state: dict) -> None:
    # Mirrors the executor: 'spawn' (EndCurrentAgentAndSpawnNewAgent) replaces the
    # active agent's pane under the SAME name; 'spawnconcurrent' (SpawnNewAgent)
    # registers a new named agent and makes it active.
    state["agent_index"] += 1
    if step["action"] == "spawn":
        # Fresh session under the same name: prior Says are unreachable to Rewind.
        state["says_by_agent"][state["active"]] = 0
        return
    newAgentName = step["payload"].strip() or f"a{state['agent_index']}"
    state["agents"].add(newAgentName)
    state["says_by_agent"].setdefault(newAgentName, 0)
    state["active"] = newAgentName


def lintScenario_applyStepEffects(step: dict, targetName: str, state: dict) -> None:
    action = step["action"]
    if action in SAY_ACTIONS:
        state["says_by_agent"][targetName] += 1
    if action == "exit":
        state["exit_agents"].add(targetName)
    if action == "record":
        state["record_agents"].add(targetName)
    if action in ("spawn", "spawnconcurrent"):
        lintScenario_applySpawnToAgentState(step, state)


def lintScenario_walkAgentTargets(parsed: dict) -> tuple[list[str], dict]:
    findings: list[str] = []
    state = lintScenario_createAgentWalkState()
    for step in parsed["steps"]:
        if step["action"] == "unknown":
            continue  # already reported by check 2
        targetName, targetFinding = lintScenario_resolveStepTarget(step, state)
        if targetFinding is not None:
            findings.append(targetFinding)
            continue  # don't let an unknown name poison the walk state
        state["active"] = targetName
        rewindFinding = lintScenario_checkRewindStep(step, targetName, state)
        if rewindFinding is not None:
            findings.append(rewindFinding)
        lintScenario_applyStepEffects(step, targetName, state)
    return findings, state


def lintScenario_checkSpawnRoots(parsed: dict) -> list[str]:
    # A spawn step's `in <root>` must name a root declared in the header (task 169) —
    # the executor fails loudly at runtime, so catch the typo at lint time.
    declaredNames = {root["name"] for root in parsed.get("roots", [])}
    findings = []
    for step in parsed["steps"]:
        rootName = step.get("root")
        if not rootName:
            continue
        if rootName not in declaredNames:
            findings.append(f"step {step['step_num']}: spawn targets undeclared root '{rootName}'")
    return findings


def lintScenario_checkExitRecordPerAgent(state: dict) -> list[str]:
    findings = []
    for agentName in sorted(state["agents"]):
        if agentName not in state["exit_agents"]:
            findings.append(f"agent @{agentName}: no Exit step resolves to this agent")
        if agentName not in state["record_agents"]:
            findings.append(f"agent @{agentName}: no Record step resolves to this agent")
    return findings


def lintScenario_lintFile(scenario_path: str) -> list[str]:
    text = Path(scenario_path).read_text()
    parsed = runScenario_convertTxtToJson(scenario_path)
    findings = lintScenario_checkHeaderFields(parsed)
    findings += lintScenario_checkUnknownSteps(parsed)
    findings += lintScenario_checkWrittenStepNumbers(text)
    findings += lintScenario_checkSpawnRoots(parsed)
    walkFindings, walkState = lintScenario_walkAgentTargets(parsed)
    findings += walkFindings
    findings += lintScenario_checkExitRecordPerAgent(walkState)
    return findings


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lint-scenario.py <scenario.txt> [<more.txt> ...]", file=sys.stderr)
        return 2
    exitCode = 0
    for scenario_path in sys.argv[1:]:
        findings = lintScenario_lintFile(scenario_path)
        if not findings:
            print(f"{scenario_path}: OK")
            continue
        exitCode = 1
        for finding in findings:
            print(f"{scenario_path}: {finding}")
    return exitCode


if __name__ == "__main__":
    sys.exit(main())
