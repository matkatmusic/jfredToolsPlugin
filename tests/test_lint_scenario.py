"""Tests for tools/lint-scenario.py — the pre-run scenario file linter."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def loadLintScenarioModule():
    # The linter filename contains a hyphen, so import it by path.
    module_path = Path(__file__).resolve().parents[1] / "tools" / "lint-scenario.py"
    spec = importlib.util.spec_from_file_location("lint_scenario", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint_scenario = loadLintScenarioModule()


DEFAULT_HEADER_LINES = ["session: lint-test", "model: claude-test", "ponytail: ultra"]

CLEAN_STEP_LINES = [
    "- [ ] 1. Say: `hello`",
    "- [ ] 2. Exit",
    "- [ ] 3. Record",
]


def writeScenarioFile(tmp_path: Path, step_lines: list[str], header_lines: list[str] | None = None) -> str:
    chosen_header = DEFAULT_HEADER_LINES if header_lines is None else header_lines
    content = "\n".join(chosen_header) + "\n---\n" + "\n".join(step_lines) + "\n"
    scenario_path = tmp_path / "scenario.txt"
    scenario_path.write_text(content)
    return str(scenario_path)


# ── clean pass ───────────────────────────────────────────────────────


def test_cleanScenarioProducesNoFindings(tmp_path: Path):
    # Scenario: a minimal well-formed file — full header, one Say, an Exit and a
    # Record that both resolve to the implicit a1 agent.
    scenario_path = writeScenarioFile(tmp_path, CLEAN_STEP_LINES)
    # The linter should report nothing.
    assert lint_scenario.lintScenario_lintFile(scenario_path) == []


# ── header fields ────────────────────────────────────────────────────


def test_missingHeaderFieldIsReported(tmp_path: Path):
    # Scenario: the header lacks its `ponytail:` line.
    header_without_ponytail = ["session: lint-test", "model: claude-test"]
    scenario_path = writeScenarioFile(tmp_path, CLEAN_STEP_LINES, header_without_ponytail)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # The missing field should be named in a header finding.
    assert any("ponytail" in finding for finding in findings)


# ── unknown steps ────────────────────────────────────────────────────


def test_unknownStepIsReported(tmp_path: Path):
    # Scenario: step 2 uses a verb the runner's parser does not know.
    step_lines = [
        "- [ ] 1. Say: `hello`",
        "- [ ] 2. Frobnicate: x",
        "- [ ] 3. Exit",
        "- [ ] 4. Record",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # The unparseable step should be reported by its step number.
    assert any("step 2" in finding for finding in findings)
    assert any("unparseable" in finding for finding in findings)


# ── written step numbers ─────────────────────────────────────────────


def test_misnumberedStepIsReported(tmp_path: Path):
    # Scenario: the second step line is written as "3." — its parse order is 2.
    step_lines = [
        "- [ ] 1. Say: `hello`",
        "- [ ] 3. Exit",
        "- [ ] 3. Record",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # The out-of-order written number should be reported against parse order 2.
    assert any("written number 3" in finding for finding in findings)
    assert any("step 2" in finding for finding in findings)


# ── agent targeting ──────────────────────────────────────────────────


def test_sayTargetingUnspawnedAgentIsReported(tmp_path: Path):
    # Scenario: a Say targets @a2 but no spawn step ever created a2.
    step_lines = [
        "- [ ] 1. Say @a2: `hi`",
        "- [ ] 2. Exit",
        "- [ ] 3. Record",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # The unspawned target should be reported by name.
    assert any("unspawned" in finding for finding in findings)
    assert any("a2" in finding for finding in findings)


# ── Exit / Record per agent ──────────────────────────────────────────


def test_spawnedAgentMissingExitIsReported(tmp_path: Path):
    # Scenario: a2 is spawned and used, gets a Record but never an Exit.
    step_lines = [
        "- [ ] 1. Say: `hello`",
        "- [ ] 2. SpawnNewAgent: a2",
        "- [ ] 3. Say @a2: `hi`",
        "- [ ] 4. Record @a2",
        "- [ ] 5. Exit @a1",
        "- [ ] 6. Record @a1",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # Only a2's missing Exit should be reported.
    assert any("a2" in finding and "no Exit" in finding for finding in findings)
    assert not any("no Record" in finding for finding in findings)


def test_spawnedAgentMissingRecordIsReported(tmp_path: Path):
    # Scenario: a2 is spawned and used, gets an Exit but never a Record.
    step_lines = [
        "- [ ] 1. Say: `hello`",
        "- [ ] 2. SpawnNewAgent: a2",
        "- [ ] 3. Say @a2: `hi`",
        "- [ ] 4. Exit @a2",
        "- [ ] 5. Exit @a1",
        "- [ ] 6. Record @a1",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # Only a2's missing Record should be reported.
    assert any("a2" in finding and "no Record" in finding for finding in findings)
    assert not any("no Exit" in finding for finding in findings)


# ── Rewind payloads ──────────────────────────────────────────────────


def test_malformedRewindPayloadIsReported(tmp_path: Path):
    # Scenario: a Rewind payload that is not of the "<N>[, code]" form.
    step_lines = [
        "- [ ] 1. Say: `hello`",
        "- [ ] 2. Rewind: abc",
        "- [ ] 3. Exit",
        "- [ ] 4. Record",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # The malformed payload should be reported against step 2.
    assert any("step 2" in finding and "Rewind" in finding for finding in findings)


def test_rewindDeeperThanPriorSaysIsReported(tmp_path: Path):
    # Scenario: Rewind 5 after only one Say on the target agent.
    step_lines = [
        "- [ ] 1. Say: `hello`",
        "- [ ] 2. Rewind: 5",
        "- [ ] 3. Exit",
        "- [ ] 4. Record",
    ]
    scenario_path = writeScenarioFile(tmp_path, step_lines)
    findings = lint_scenario.lintScenario_lintFile(scenario_path)
    # The over-deep rewind should be reported with both counts.
    assert any("exceeds" in finding for finding in findings)
