"""Tests for run_scenario_lib.py hook handlers and launch function."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import common.scripts.run_scenario_lib as run_scenario_lib


# ── runScenario_sessionStart ─────────────────────────────────────────


def test_sessionStart_creates_ready_file(tmp_path: Path):
    # Scenario: SessionStart hook fires and should create a "ready" signal file.
    # The signal_dir exists but the "ready" file does not.
    signal_dir = str(tmp_path / "signal")
    Path(signal_dir).mkdir()

    from common.scripts.run_scenario_lib import runScenario_sessionStart

    rc = runScenario_sessionStart(signal_dir)

    # The "ready" file should exist after the handler runs.
    assert (Path(signal_dir) / "ready").is_file()
    assert rc == 0


def test_sessionStart_returns_zero_when_signal_dir_missing(tmp_path: Path):
    # Scenario: signal_dir does not exist. Handler should not crash.
    signal_dir = str(tmp_path / "nonexistent")

    from common.scripts.run_scenario_lib import runScenario_sessionStart

    rc = runScenario_sessionStart(signal_dir)

    assert rc == 0


# ── runScenario_stop ─────────────────────────────────────────────────


def test_stop_creates_done_file(tmp_path: Path):
    # Scenario: Stop hook fires and should create a "done" signal file.
    signal_dir = str(tmp_path / "signal")
    Path(signal_dir).mkdir()

    from common.scripts.run_scenario_lib import runScenario_stop

    rc = runScenario_stop(signal_dir)

    # The "done" file should exist after the handler runs.
    assert (Path(signal_dir) / "done").is_file()
    assert rc == 0


def test_stop_done_file_contains_timestamp(tmp_path: Path):
    # Scenario: The "done" file should contain a timestamp so the orchestrator
    # can distinguish fresh signals from stale ones.
    signal_dir = str(tmp_path / "signal")
    Path(signal_dir).mkdir()

    from common.scripts.run_scenario_lib import runScenario_stop

    runScenario_stop(signal_dir)

    content = (Path(signal_dir) / "done").read_text().strip()
    # The timestamp should be a non-empty string.
    assert len(content) > 0


def test_stop_returns_zero_when_signal_dir_missing(tmp_path: Path):
    # Scenario: signal_dir does not exist. Handler should not crash.
    signal_dir = str(tmp_path / "nonexistent")

    from common.scripts.run_scenario_lib import runScenario_stop

    rc = runScenario_stop(signal_dir)

    assert rc == 0


# ── runScenario_sessionEnd ───────────────────────────────────────────


def test_sessionEnd_writes_transcript_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: SessionEnd hook fires with transcript_path in stdin JSON.
    # The handler should write the transcript_path to jsonl_path.txt.
    signal_dir = str(tmp_path / "signal")
    Path(signal_dir).mkdir()

    transcript = "/Users/test/.claude/projects/abc/123.jsonl"
    payload = json.dumps({
        "session_id": "abc123",
        "transcript_path": transcript,
        "hook_event_name": "SessionEnd",
        "reason": "prompt_input_exit",
    })

    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    from common.scripts.run_scenario_lib import runScenario_sessionEnd

    rc = runScenario_sessionEnd(signal_dir)

    jsonl_path_file = Path(signal_dir) / "jsonl_path.txt"
    assert jsonl_path_file.is_file()
    assert jsonl_path_file.read_text().strip() == transcript
    assert rc == 0


def test_sessionEnd_handles_missing_transcript_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: SessionEnd fires but transcript_path is missing from payload.
    signal_dir = str(tmp_path / "signal")
    Path(signal_dir).mkdir()

    payload = json.dumps({
        "session_id": "abc123",
        "hook_event_name": "SessionEnd",
    })

    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    from common.scripts.run_scenario_lib import runScenario_sessionEnd

    rc = runScenario_sessionEnd(signal_dir)

    # Should still return 0 and not crash.
    assert rc == 0


def test_sessionEnd_handles_empty_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: SessionEnd fires with empty stdin (malformed hook call).
    signal_dir = str(tmp_path / "signal")
    Path(signal_dir).mkdir()

    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    from common.scripts.run_scenario_lib import runScenario_sessionEnd

    rc = runScenario_sessionEnd(signal_dir)

    assert rc == 0


def test_sessionEnd_returns_zero_when_signal_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: signal_dir does not exist. Handler should not crash.
    signal_dir = str(tmp_path / "nonexistent")

    payload = json.dumps({
        "session_id": "abc123",
        "transcript_path": "/some/path.jsonl",
        "hook_event_name": "SessionEnd",
    })

    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    from common.scripts.run_scenario_lib import runScenario_sessionEnd

    rc = runScenario_sessionEnd(signal_dir)

    assert rc == 0


# ── runScenario_launch ───────────────────────────────────────────────


class _SuccessfulFileLock:
    def __init__(self, _path, timeout=10):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _installLaunchDoubles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    pane_id: str = "%99",
) -> list[tuple]:
    """Stub all external dependencies for runScenario_launch."""
    calls: list[tuple] = []
    invocation_dir = tmp_path / "run-scenario.inv"
    invocation_dir.mkdir(exist_ok=True)

    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir(exist_ok=True)
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir(exist_ok=True)

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setattr(run_scenario_lib.tempfile, "mkdtemp", lambda prefix: str(invocation_dir))
    monkeypatch.setattr(run_scenario_lib, "FileLock", _SuccessfulFileLock)
    monkeypatch.setattr(run_scenario_lib, "bgPermissions_loadClaude", lambda *_a, **_k: '["Read(**)"]')
    monkeypatch.setattr(run_scenario_lib, "claude_buildCmd", lambda *_args: "claude --fake\n")
    monkeypatch.setattr(run_scenario_lib, "tmux_newSession", lambda *args: calls.append(("new_session", args)) or 0)
    monkeypatch.setattr(run_scenario_lib, "tmux_capturePane", lambda *args: "")
    monkeypatch.setattr(run_scenario_lib, "tmux_sendEnter", lambda *args: 0)
    monkeypatch.setattr(run_scenario_lib, "tmux_sendAndSubmit", lambda *args: calls.append(("send", args)) or 0)
    monkeypatch.setattr(run_scenario_lib.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(run_scenario_lib, "terminal_spawnIfNeeded", lambda *args, **kw: calls.append(("terminal", args)))
    monkeypatch.setattr(run_scenario_lib, "_waitForSignalFile", lambda *args, **kw: True)

    # Create a scenario file for launch to copy.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text("cwd: /tmp\n---\n- [ ] 1. Say: `hello`\n")

    return calls


def test_launch_creates_hooks_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: runScenario_launch should write a hooks.json file in the tmpdir
    # that wires SessionStart, Stop, and SessionEnd to the orchestrator.
    calls = _installLaunchDoubles(monkeypatch, tmp_path)

    from common.scripts.run_scenario_lib import runScenario_launch

    result = runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    assert isinstance(result, dict)
    assert "signal_dir" in result
    invocation_dir = tmp_path / "run-scenario.inv"
    hooks_file = invocation_dir / "hooks.json"
    assert hooks_file.is_file()
    hooks_data = json.loads(hooks_file.read_text())
    assert "SessionStart" in hooks_data
    assert "Stop" in hooks_data
    assert "SessionEnd" in hooks_data


def test_launch_calls_claude_buildCmd_with_settings_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: runScenario_launch should call claude_buildCmd with
    # a settings.json path inside the invocation tmpdir.
    _installLaunchDoubles(monkeypatch, tmp_path)
    build_cmd_args: list = []
    monkeypatch.setattr(
        run_scenario_lib, "claude_buildCmd",
        lambda *args: (build_cmd_args.append(args), "claude --fake\n")[1],
    )

    from common.scripts.run_scenario_lib import runScenario_launch

    runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    assert len(build_cmd_args) == 1
    settings_path = build_cmd_args[0][0]
    assert "run-scenario.inv" in settings_path
    assert settings_path.endswith("settings.json")


def test_launch_creates_tmux_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: runScenario_launch should create a tmux session
    # with the given session name.
    calls = _installLaunchDoubles(monkeypatch, tmp_path)

    from common.scripts.run_scenario_lib import runScenario_launch

    runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    session_calls = [c for c in calls if c[0] == "new_session"]
    assert len(session_calls) == 1
    assert session_calls[0][1][0] == "test-session"


def test_launch_opens_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: runScenario_launch should call terminal_spawnIfNeeded
    # to open Terminal.app attached to the session.
    calls = _installLaunchDoubles(monkeypatch, tmp_path)

    from common.scripts.run_scenario_lib import runScenario_launch

    runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    terminal_calls = [c for c in calls if c[0] == "terminal"]
    assert len(terminal_calls) == 1


def test_launch_dismisses_folder_trust_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: If the tmux pane shows "trust this folder", the launcher
    # should send Enter to dismiss it.
    calls = _installLaunchDoubles(monkeypatch, tmp_path)
    enter_calls: list = []
    monkeypatch.setattr(run_scenario_lib, "tmux_capturePane", lambda *args: "trust this folder")
    monkeypatch.setattr(run_scenario_lib, "tmux_sendEnter", lambda *args: enter_calls.append(args) or 0)

    from common.scripts.run_scenario_lib import runScenario_launch

    runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    assert len(enter_calls) >= 1


# ── runScenario_parseScenario ────────────────────────────────────────


def test_parseScenario_extracts_steps(tmp_path: Path):
    # Scenario: A well-formed scenario file should yield a list of steps.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "---\n"
        "- [ ] 1. Say: `hello world`\n"
        "- [ ] 2. Edit: foo.py — prepend `# comment` as first line\n"
        "- [ ] 3. Rewind: 2\n"
        "- [ ] 4. Exit\n"
        "- [ ] 5. Record: JSONL filename\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert len(result["steps"]) == 5
    assert result["steps"][0]["action"] == "say"
    assert result["steps"][0]["payload"] == "hello world"
    assert result["steps"][1]["action"] == "edit"
    assert result["steps"][2]["action"] == "rewind"
    assert result["steps"][3]["action"] == "exit"
    assert result["steps"][4]["action"] == "record"


def test_parseScenario_extracts_backtick_text_from_say(tmp_path: Path):
    # Scenario: Say payload should extract text from between backticks.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. Say: `Write a file called foo.py`\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["payload"] == "Write a file called foo.py"


def test_parseScenario_say_without_backticks_uses_raw_text(tmp_path: Path):
    # Scenario: If Say has no backticks, use the entire text after "Say:".
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. Say: hello there\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["payload"] == "hello there"


def test_parseScenario_recognizes_sayqueued_action(tmp_path: Path):
    # Scenario: a "SayQueued:" line parses to action "sayqueued".
    # Step: write a scenario whose only step is a SayQueued line.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. SayQueued: `also add a docstring`\n"
    )
    from common.scripts.run_scenario_lib import runScenario_parseScenario
    # Step: parse it.
    result = runScenario_parseScenario(str(scenario))
    # Verify: the action is "sayqueued".
    assert result["steps"][0]["action"] == "sayqueued"


def test_parseScenario_extracts_backtick_text_from_sayqueued(tmp_path: Path):
    # Scenario: SayQueued honors the same backtick-extraction convention as Say.
    # Step: write a SayQueued line whose payload is wrapped in backticks.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. SayQueued: `also add a docstring`\n"
    )
    from common.scripts.run_scenario_lib import runScenario_parseScenario
    # Step: parse it.
    result = runScenario_parseScenario(str(scenario))
    # Verify: payload is the inner backtick text only.
    assert result["steps"][0]["payload"] == "also add a docstring"


def test_parseScenario_wait_action(tmp_path: Path):
    # Scenario: "Wait" lines should parse as action "wait".
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. Wait for Claude to finish.\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["action"] == "wait"


def test_parseScenario_spawn_action(tmp_path: Path):
    # Scenario: "EndCurrentAgentAndSpawnNewAgent" lines normalize to action "spawn".
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. EndCurrentAgentAndSpawnNewAgent: --excludeJSONL\n"
        "- [ ] 2. EndCurrentAgentAndSpawnNewAgent\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["action"] == "spawn"
    assert result["steps"][0]["payload"] == "--excludeJSONL"
    assert result["steps"][1]["action"] == "spawn"
    assert result["steps"][1]["payload"] == ""


def test_parseScenario_spawnNewAgentActionIsRecognized(tmp_path: Path):
    # Scenario: a "SpawnNewAgent: a2" line parses to action "spawnconcurrent"
    # with the new agent's name "a2" as the payload.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "session: t\n---\n"
        "- [ ] 1. SpawnNewAgent: a2\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["action"] == "spawnconcurrent"
    assert result["steps"][0]["payload"] == "a2"


def test_parseScenario_extractsAgentTargetToken(tmp_path: Path):
    # Scenario: "Say @a2: `hi`" parses target "a2" and payload "hi";
    # a plain "Say: `ho`" parses target None.
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "session: t\n---\n"
        "- [ ] 1. Say @a2: `hi`\n"
        "- [ ] 2. Say: `ho`\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["target"] == "a2"
    assert result["steps"][0]["payload"] == "hi"
    assert result["steps"][1]["target"] is None
    assert result["steps"][1]["payload"] == "ho"


def test_snapshotAbandonedBranch_copies_files_and_writes_manifest(tmp_path: Path):
    # Scenario: snapshotting before a rewind captures working files, skips runner
    # artifacts, and records a manifest describing the abandoned branch.
    import json as _json
    from common.scripts.run_scenario_lib import _snapshotAbandonedBranch

    cwd = tmp_path / "work"
    (cwd / "tests").mkdir(parents=True)
    (cwd / "mod.py").write_text("def f(): return 1\n")
    (cwd / "tests" / "test_mod.py").write_text("assert True\n")
    (cwd / "settings.json").write_text("{}")        # runner artifact, should be skipped
    (cwd / "ready").write_text("1")                 # signal file, should be skipped

    dest = _snapshotAbandonedBranch(str(cwd), 1, 5, "2, code")

    snap = Path(dest)
    assert snap.name == "abandoned-branch-1"
    assert (snap / "mod.py").read_text() == "def f(): return 1\n"
    assert (snap / "tests" / "test_mod.py").is_file()
    assert not (snap / "settings.json").exists()
    assert not (snap / "ready").exists()

    manifest = _json.loads((snap / "manifest.json").read_text())
    assert manifest["label"] == "abandoned-branch-1"
    assert manifest["step_num"] == 5
    assert manifest["code_rewind"] is True
    assert "mod.py" in manifest["files"]


def test_parseScenario_unknown_action(tmp_path: Path):
    # Scenario: Unrecognized action should parse as "unknown".
    scenario = tmp_path / "scenario.txt"
    scenario.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. Dance: do a jig\n"
    )

    from common.scripts.run_scenario_lib import runScenario_parseScenario

    result = runScenario_parseScenario(str(scenario))

    assert result["steps"][0]["action"] == "unknown"


# ── runScenario_executeSteps ─────────────────────────────────────────


def _installExecutorDoubles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Stub tmux functions for executor tests. Returns tracking dict."""
    signal_dir = tmp_path / "signal"
    tracking = {
        "sent": [],
        "sent_with_pane": [],
        "killed_sessions": [],
        "signal_cleared": 0,
        "pane_captures": [],
    }

    def fake_sendAndSubmit(pane, text):
        tracking["sent"].append(text)
        tracking["sent_with_pane"].append((text, pane))
        # Simulate Stop hook firing after a prompt is sent.
        (signal_dir / "done").write_text("1234")
        return 0

    def fake_hasSession(session_name):
        # Default: report sessions as already gone (return code 1) so end-of-run
        # cleanup is a no-op unless a test overrides this.
        return 1

    def fake_killSession(session_name):
        tracking["killed_sessions"].append(session_name)
        return 0

    def fake_sendKeys(pane, keys):
        tracking["sent"].append(f"KEYS:{keys}")
        return 0

    def fake_sendEnter(pane):
        tracking["sent"].append("ENTER")
        return 0

    def fake_capturePane(pane, lines=None):
        return "❯"

    def fake_waitForClaudeReadiness(pane, timeout=30):
        return 0

    monkeypatch.setattr(run_scenario_lib, "tmux_sendAndSubmit", fake_sendAndSubmit)
    monkeypatch.setattr(run_scenario_lib, "tmux_hasSession", fake_hasSession)
    monkeypatch.setattr(run_scenario_lib, "tmux_killSession", fake_killSession)
    monkeypatch.setattr(run_scenario_lib, "tmux_sendKeys", fake_sendKeys)
    monkeypatch.setattr(run_scenario_lib, "tmux_sendEnter", fake_sendEnter)
    monkeypatch.setattr(run_scenario_lib, "tmux_capturePane", fake_capturePane)
    monkeypatch.setattr(run_scenario_lib, "tmux_waitForClaudeReadiness", fake_waitForClaudeReadiness)
    # Make sleep a no-op and timeout short for fast tests.
    monkeypatch.setattr(run_scenario_lib.time, "sleep", lambda _: None)
    monkeypatch.setattr(run_scenario_lib, "SIGNAL_POLL_TIMEOUT_S", 2)
    monkeypatch.setattr(run_scenario_lib, "SIGNAL_POLL_INTERVAL_S", 0)

    return tracking


def test_executeSteps_say_sends_prompt_and_waits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: A Say step should send the prompt text to tmux
    # and wait for the done signal file.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. Say: `hello`\n")
    # Pre-create the done file so the wait returns immediately.
    (signal_dir / "done").write_text("1234")

    steps = [{"action": "say", "payload": "hello", "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert "hello" in tracking["sent"]


def test_executeSteps_sayqueued_sends_queued_prompt_after_say(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: a Say immediately followed by a SayQueued sends both prompts,
    # in order, and completes.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text(
        "- [ ] 1. Say: `first`\n"
        "- [ ] 2. SayQueued: `queued`\n"
    )
    # Pre-create done so both waits return immediately.
    (signal_dir / "done").write_text("1234")
    steps = [
        {"action": "say", "payload": "first", "step_num": 1},
        {"action": "sayqueued", "payload": "queued", "step_num": 2},
    ]
    from common.scripts.run_scenario_lib import runScenario_executeSteps
    # Step: run the two steps.
    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)
    # Verify: the run completed.
    assert result["completed"] is True
    # Verify: both prompts were sent, the queued one after the say one.
    assert tracking["sent"] == ["first", "queued"]


def test_executeSteps_resumes_from_start_from(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: Calling with start_from should skip earlier steps.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text(
        "- [x] 1. Say: `hello`\n"
        "- [ ] 2. Say: `bye`\n"
    )
    (signal_dir / "done").write_text("1234")

    steps = [
        {"action": "say", "payload": "hello", "step_num": 1},
        {"action": "say", "payload": "bye", "step_num": 2},
    ]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps, start_from=1)

    assert result["completed"] is True
    assert "bye" in tracking["sent"]
    assert "hello" not in tracking["sent"]


def test_executeSteps_exit_sends_exit_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: An Exit step should send /exit to tmux.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. Exit\n")

    steps = [{"action": "exit", "payload": "", "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert "/exit" in tracking["sent"]


def test_executeSteps_record_reads_jsonl_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: A Record step should read jsonl_path.txt and include
    # the path in the result.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "jsonl_path.txt").write_text("/path/to/transcript.jsonl")
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. Record: JSONL filename\n")

    steps = [{"action": "record", "payload": "JSONL filename", "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert result["jsonl_path"] == "/path/to/transcript.jsonl"


def test_executeSteps_rewind_sends_full_sequence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: A Rewind step should send /rewind, press Up N times,
    # press Enter to select, send menu key, then glyph poll + Ctrl-U.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. Rewind: 2, code\n")

    steps = [{"action": "rewind", "payload": "2, code", "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert "/rewind" in tracking["sent"]
    assert tracking["sent"].count("KEYS:Up") == 2
    assert "KEYS:1" in tracking["sent"]
    assert "KEYS:C-u" in tracking["sent"]


def test_executeSteps_rewind_conversation_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: Conversation-only rewind when code WAS changed at the rewind
    # point should send menu key "2" (option 2 = conversation only).
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    monkeypatch.setattr(
        run_scenario_lib,
        "tmux_capturePane",
        lambda *args: "  1. Restore code and conversation\n  2. Restore conversation\n❯",
    )
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. Rewind: 1\n")

    steps = [{"action": "rewind", "payload": "1", "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert "/rewind" in tracking["sent"]
    assert tracking["sent"].count("KEYS:Up") == 1
    assert "KEYS:2" in tracking["sent"]


def test_executeSteps_compact_waitsForCompactionDoneHook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: a /compact step must block until the SessionStart-on-compact hook
    # re-touches `ready`, NOT just on a readiness glyph. We pre-stage `ready`,
    # assert the step clears it first, and have the send simulate the hook firing.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "ready").write_text("stale")  # leftover from session start
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. /compact\n")
    observed = {"ready_present_at_send": None}

    def fake_compact_send(pane, text):
        tracking["sent"].append(text)
        # The pre-staged `ready` must have been cleared before /compact is sent.
        observed["ready_present_at_send"] = (signal_dir / "ready").is_file()
        # Simulate the SessionStart-on-compact hook firing when compaction finishes.
        (signal_dir / "ready").write_text(str(1))
        return 0

    monkeypatch.setattr(run_scenario_lib, "tmux_sendAndSubmit", fake_compact_send)

    steps = [{"action": "compact", "payload": "", "target": None, "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert "/compact" in tracking["sent"]
    assert observed["ready_present_at_send"] is False  # cleared before sending


def test_executeSteps_clear_waitsForClearDoneHook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: a /clear step blocks until the SessionStart-on-clear hook
    # re-touches `ready`, mirroring the /compact behavior.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "ready").write_text("stale")
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. /clear\n")
    observed = {"ready_present_at_send": None}

    def fake_clear_send(pane, text):
        tracking["sent"].append(text)
        observed["ready_present_at_send"] = (signal_dir / "ready").is_file()
        (signal_dir / "ready").write_text(str(1))
        return 0

    monkeypatch.setattr(run_scenario_lib, "tmux_sendAndSubmit", fake_clear_send)

    steps = [{"action": "clear", "payload": "", "target": None, "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    assert result["completed"] is True
    assert "/clear" in tracking["sent"]
    assert observed["ready_present_at_send"] is False


def test_parseScenario_compact_and_clear_steps():
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("session: test\n---\n")
        f.write("- [ ] 1. Say: `hello`\n")
        f.write("- [ ] 2. /compact\n")
        f.write("- [ ] 3. /clear\n")
        f.write("- [ ] 4. Exit\n")
        f.name

    from common.scripts.run_scenario_lib import runScenario_convertTxtToJson

    result = runScenario_convertTxtToJson(f.name)
    Path(f.name).unlink()

    assert result["steps"][0]["action"] == "say"
    assert result["steps"][1]["action"] == "compact"
    assert result["steps"][1]["payload"] == ""
    assert result["steps"][2]["action"] == "clear"
    assert result["steps"][2]["payload"] == ""
    assert result["steps"][3]["action"] == "exit"


def test_executeSteps_marks_checkboxes_in_progress_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: Completed steps should be marked [x] in the progress file.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1234")
    progress_file = tmp_path / "progress.md"
    progress_file.write_text(
        "cwd: /tmp\n"
        "---\n"
        "- [ ] 1. Say: `hello`\n"
        "- [ ] 2. Exit\n"
    )

    steps = [
        {"action": "say", "payload": "hello", "step_num": 1},
        {"action": "exit", "payload": "", "step_num": 2},
    ]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    runScenario_executeSteps(str(signal_dir), "test:main", str(progress_file), steps)

    content = progress_file.read_text()
    assert "- [x] 1." in content
    assert "- [x] 2." in content


def test_executeSpawnConcurrent_doesNotKillPriorSession(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: running a SpawnNewAgent step must NOT tear down the current
    # agent's tmux session; it spawns a second live session instead.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1")
    progress_file = tmp_path / "p.md"
    progress_file.write_text("- [ ] 1. SpawnNewAgent: a2\n")
    monkeypatch.setattr(
        run_scenario_lib, "_spawnClaudeInTmux",
        lambda session, cwd, settings, model="": f"{session}:main",
    )

    steps = [{"action": "spawnconcurrent", "payload": "a2", "target": None, "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(
        str(signal_dir), "t:main", str(progress_file), steps,
        cwd=str(tmp_path), session_name="t",
    )

    assert result["completed"] is True
    # The prior agent ("t") was reported gone by the default hasSession stub,
    # so end-of-run cleanup killed nothing — and the spawn itself killed nothing.
    assert tracking["killed_sessions"] == []


def test_executeSteps_routesSayToTargetedAgentPane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: after spawning a2, an untargeted "Say" goes to the most-recently
    # addressed agent (a2), and "Say @a1" sends to a1's original pane.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1")
    progress_file = tmp_path / "p.md"
    progress_file.write_text("x\n")
    monkeypatch.setattr(
        run_scenario_lib, "_spawnClaudeInTmux",
        lambda session, cwd, settings, model="": f"{session}:main",
    )

    steps = [
        {"action": "spawnconcurrent", "payload": "a2", "target": None, "step_num": 1},
        {"action": "say", "payload": "to-two", "target": None, "step_num": 2},
        {"action": "say", "payload": "to-one", "target": "a1", "step_num": 3},
    ]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    runScenario_executeSteps(
        str(signal_dir), "t:main", str(progress_file), steps,
        cwd=str(tmp_path), session_name="t",
    )

    sent_by_pane = dict(tracking["sent_with_pane"])
    assert sent_by_pane["to-two"] == "t-a2:main"   # untargeted → active agent a2
    assert sent_by_pane["to-one"] == "t:main"      # @a1 → original pane


def test_executeSteps_recordTargetedAgentCapturesItsTranscript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: with two agents, "Record @a1" then "Record @a2" land BOTH
    # transcripts in jsonl_paths, regardless of who fired Stop last.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "p.md"
    progress_file.write_text("x\n")
    monkeypatch.setattr(
        run_scenario_lib, "_spawnClaudeInTmux",
        lambda session, cwd, settings, model="": f"{session}:main",
    )

    # Each Say leaves a distinct transcript path in jsonl_path.txt, as the real
    # Stop hook would for whichever agent just answered.
    def fake_say_then_write_transcript(pane, text):
        (signal_dir / "done").write_text("1")
        (signal_dir / "jsonl_path.txt").write_text(f"/t/{text}.jsonl")
        return 0

    monkeypatch.setattr(run_scenario_lib, "tmux_sendAndSubmit", fake_say_then_write_transcript)

    steps = [
        {"action": "say", "payload": "one", "target": "a1", "step_num": 1},
        {"action": "spawnconcurrent", "payload": "a2", "target": None, "step_num": 2},
        {"action": "say", "payload": "two", "target": "a2", "step_num": 3},
        {"action": "record", "payload": "", "target": "a1", "step_num": 4},
        {"action": "record", "payload": "", "target": "a2", "step_num": 5},
    ]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(
        str(signal_dir), "t:main", str(progress_file), steps,
        cwd=str(tmp_path), session_name="t",
    )

    assert "/t/one.jsonl" in result["jsonl_paths"]
    assert "/t/two.jsonl" in result["jsonl_paths"]


def test_executeSteps_killsRemainingAgentSessionsAtEnd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: after a concurrent run finishes, every registered agent session
    # that is still alive is killed so re-runs don't hit duplicate session names.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    monkeypatch.setattr(run_scenario_lib, "tmux_hasSession", lambda s: 0)  # 0 == still alive
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1")
    progress_file = tmp_path / "p.md"
    progress_file.write_text("x\n")
    monkeypatch.setattr(
        run_scenario_lib, "_spawnClaudeInTmux",
        lambda session, cwd, settings, model="": f"{session}:main",
    )

    steps = [{"action": "spawnconcurrent", "payload": "a2", "target": None, "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    runScenario_executeSteps(
        str(signal_dir), "t:main", str(progress_file), steps,
        cwd=str(tmp_path), session_name="t",
    )

    assert "t" in tracking["killed_sessions"]       # original a1 session
    assert "t-a2" in tracking["killed_sessions"]    # spawned a2 session


def test_executeSteps_excludeJsonlOmitsPriorAgentTranscript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: a killing spawn carrying --excludeJSONL must NOT add the first
    # agent's transcript to jsonl_paths (s39-s44 depend on this).
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1")
    (signal_dir / "jsonl_path.txt").write_text("/t/first.jsonl")
    progress_file = tmp_path / "p.md"
    progress_file.write_text("x\n")
    monkeypatch.setattr(
        run_scenario_lib, "_spawnClaudeInTmux",
        lambda session, cwd, settings, model="": f"{session}:main",
    )

    steps = [{"action": "spawn", "payload": "--excludeJSONL", "target": None, "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(
        str(signal_dir), "t:main", str(progress_file), steps,
        cwd=str(tmp_path), session_name="t",
    )

    assert "/t/first.jsonl" not in result["jsonl_paths"]


# ── _executeEdit ─────────────────────────────────────────────────────


def test_executeEdit_prepend(tmp_path: Path):
    # Scenario: "prepend `# user edit`" should insert the comment as the first line.
    target = tmp_path / "foo.py"
    target.write_text("def hello():\n    pass\n")

    from common.scripts.run_scenario_lib import _executeEdit

    _executeEdit(str(tmp_path), "foo.py — prepend `# user edit`")

    lines = target.read_text().splitlines()
    assert lines[0] == "# user edit"
    assert lines[1] == "def hello():"


def test_executeEdit_append(tmp_path: Path):
    # Scenario: "append `# end of file`" should add the comment as the last line.
    target = tmp_path / "foo.py"
    target.write_text("def hello():\n    pass\n")

    from common.scripts.run_scenario_lib import _executeEdit

    _executeEdit(str(tmp_path), "foo.py — append `# end of file`")

    lines = target.read_text().splitlines()
    assert lines[-1] == "# end of file"


def test_executeEdit_after(tmp_path: Path):
    # Scenario: "after `def hello` insert `# inserted after`" should insert
    # the comment on the line after the marker.
    target = tmp_path / "foo.py"
    target.write_text("def hello():\n    pass\n    return 1\n")

    from common.scripts.run_scenario_lib import _executeEdit

    _executeEdit(str(tmp_path), "foo.py — after `def hello` insert `# inserted after`")

    lines = target.read_text().splitlines()
    assert lines[0] == "def hello():"
    assert lines[1] == "# inserted after"


def test_executeEdit_before(tmp_path: Path):
    # Scenario: "before `return` insert `# inserted before`" should insert
    # the comment on the line before the marker.
    target = tmp_path / "foo.py"
    target.write_text("def hello():\n    pass\n    return 1\n")

    from common.scripts.run_scenario_lib import _executeEdit

    _executeEdit(str(tmp_path), "foo.py — before `return` insert `# inserted before`")

    lines = target.read_text().splitlines()
    idx = next(i for i, l in enumerate(lines) if "return" in l)
    assert lines[idx - 1] == "# inserted before"


def test_executeSteps_edit_runs_without_pausing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: Edit steps should now execute inline (no pause) since
    # _executeEdit handles them mechanically.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1234")
    progress_file = tmp_path / "progress.md"
    progress_file.write_text(
        "- [ ] 1. Say: `hello`\n"
        "- [ ] 2. Edit: foo.py — prepend `# comment`\n"
        "- [ ] 3. Say: `bye`\n"
    )

    target = tmp_path / "foo.py"
    target.write_text("original\n")

    steps = [
        {"action": "say", "payload": "hello", "step_num": 1},
        {"action": "edit", "payload": "foo.py — prepend `# comment`", "step_num": 2},
        {"action": "say", "payload": "bye", "step_num": 3},
    ]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    # Pass cwd so _executeEdit can find the file.
    result = runScenario_executeSteps(
        str(signal_dir), "test:main", str(progress_file), steps, cwd=str(tmp_path),
    )

    assert result["completed"] is True
    assert target.read_text().startswith("# comment\n")
    assert "hello" in tracking["sent"]
    assert "bye" in tracking["sent"]


# ── _copyWorkingTree ─────────────────────────────────────────────────


def test_copyWorkingTree_copies_files_and_skips_excluded(tmp_path: Path):
    # Scenario: _copyWorkingTree copies the agent's working files into a dest dir
    # but skips runner/signal artifacts, and returns the list of copied names.
    from common.scripts.run_scenario_lib import _copyWorkingTree

    # A working tree with a module, a nested test, plus excluded runner/signal files.
    cwd = tmp_path / "work"
    (cwd / "tests").mkdir(parents=True)
    (cwd / "mod.py").write_text("def f(): return 1\n")
    (cwd / "tests" / "test_mod.py").write_text("assert True\n")
    (cwd / "settings.json").write_text("{}")   # runner artifact — must be skipped
    (cwd / "ready").write_text("1")            # signal file — must be skipped
    dest = tmp_path / "dest"
    dest.mkdir()

    captured = _copyWorkingTree(str(cwd), str(dest))

    # Real working files (incl. nested) are copied.
    assert (dest / "mod.py").read_text() == "def f(): return 1\n"
    assert (dest / "tests" / "test_mod.py").is_file()
    # Runner/signal files are not.
    assert not (dest / "settings.json").exists()
    assert not (dest / "ready").exists()
    # Return value lists the copied top-level names, excludes skipped ones.
    assert "mod.py" in captured
    assert "settings.json" not in captured


def test_copyWorkingTree_skips_step_states_and_gitignore(tmp_path: Path):
    # Scenario: a snapshot must never recursively copy prior snapshots (.step_states)
    # nor the runner-injected .gitignore — both are excluded.
    from common.scripts.run_scenario_lib import _copyWorkingTree

    cwd = tmp_path / "work"
    (cwd / ".step_states" / "step-001").mkdir(parents=True)
    (cwd / ".step_states" / "step-001" / "old.py").write_text("old\n")
    (cwd / ".gitignore").write_text(".step_states/\n")
    (cwd / "mod.py").write_text("x = 1\n")
    dest = tmp_path / "dest"
    dest.mkdir()

    captured = _copyWorkingTree(str(cwd), str(dest))

    # The real file is copied; the snapshot dir and gitignore are not.
    assert (dest / "mod.py").is_file()
    assert not (dest / ".step_states").exists()
    assert not (dest / ".gitignore").exists()
    assert ".step_states" not in captured
    assert ".gitignore" not in captured


# ── _snapshotStep ────────────────────────────────────────────────────


def test_snapshotStep_copies_files_and_writes_manifest(tmp_path: Path):
    # Scenario: snapshotting after a step captures the working files into
    # .step_states/step-<NNN>/, skips runner artifacts, and records a manifest
    # describing the step (action + payload + step_num).
    import json as _json
    from common.scripts.run_scenario_lib import _snapshotStep

    cwd = tmp_path / "work"
    cwd.mkdir()
    (cwd / "mod.py").write_text("def f(): return 1\n")
    (cwd / "ready").write_text("1")   # signal file — must be skipped

    dest = _snapshotStep(str(cwd), 1, "edit", "mod.py — prepend `# x`")

    snap = Path(dest)
    # Zero-padded step label, inside .step_states.
    assert snap.name == "step-001"
    assert snap.parent.name == ".step_states"
    # Working file captured, signal file skipped.
    assert (snap / "mod.py").read_text() == "def f(): return 1\n"
    assert not (snap / "ready").exists()
    # Manifest describes the step.
    manifest = _json.loads((snap / "manifest.json").read_text())
    assert manifest["label"] == "step-001"
    assert manifest["step_num"] == 1
    assert manifest["action"] == "edit"
    assert manifest["payload"] == "mod.py — prepend `# x`"
    assert "mod.py" in manifest["files"]


# ── runScenario_executeSteps per-step snapshots ──────────────────────


def test_executeSteps_snapshots_only_on_code_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: the executor snapshots a step ONLY when it changed code on disk.
    # Conversational Say steps ("hello"/"bye") touch no files (the fake agent writes
    # nothing), so only the Edit step — which mutates foo.py — is captured.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1234")
    progress_file = tmp_path / "progress.md"
    progress_file.write_text(
        "- [ ] 1. Say: `hello`\n"
        "- [ ] 2. Edit: foo.py — prepend `# c`\n"
        "- [ ] 3. Say: `bye`\n"
    )

    # cwd is separate from signal_dir so signal-file writes don't look like code changes.
    work = tmp_path / "work"
    work.mkdir()
    (work / "foo.py").write_text("original\n")

    steps = [
        {"action": "say", "payload": "hello", "step_num": 1},
        {"action": "edit", "payload": "foo.py — prepend `# c`", "step_num": 2},
        {"action": "say", "payload": "bye", "step_num": 3},
    ]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(
        str(signal_dir), "test:main", str(progress_file), steps, cwd=str(work),
    )

    assert result["completed"] is True
    # Only the code-changing edit step is captured; the chatter Says are not.
    assert result["step_states"] == ["step-002"]
    assert not (work / ".step_states" / "step-001").exists()
    assert not (work / ".step_states" / "step-003").exists()
    # The captured snapshot is the POST-edit state.
    import json as _json
    edit_manifest = _json.loads(
        (work / ".step_states" / "step-002" / "manifest.json").read_text()
    )
    assert edit_manifest["action"] == "edit"
    assert (work / ".step_states" / "step-002" / "foo.py").read_text().startswith("# c\n")


def test_executeSteps_rewind_does_not_snapshot_even_when_tree_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: a /rewind reverts the tree (a change), but the engine can't attribute
    # a step number to a revert, so rewind never produces a step snapshot.
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    progress_file = tmp_path / "progress.md"
    progress_file.write_text("- [ ] 1. Rewind: 1\n")

    work = tmp_path / "work"
    work.mkdir()
    (work / "foo.py").write_text("v1\n")

    # Make the rewind alter the tree so change-detection WOULD otherwise fire.
    def fake_rewind(pane, payload):
        (work / "foo.py").write_text("reverted\n")
    monkeypatch.setattr(run_scenario_lib, "_executeRewind", fake_rewind)

    steps = [{"action": "rewind", "payload": "1", "step_num": 1}]

    from common.scripts.run_scenario_lib import runScenario_executeSteps

    result = runScenario_executeSteps(
        str(signal_dir), "test:main", str(progress_file), steps, cwd=str(work),
    )

    assert result["completed"] is True
    assert result["step_states"] == []
    assert not (work / ".step_states").exists()


# ── runScenario_launch .gitignore ────────────────────────────────────


def test_launch_writes_gitignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: launch writes a .gitignore into the tmpdir so git-baseline scenarios
    # don't stage the runner's snapshot folders.
    _installLaunchDoubles(monkeypatch, tmp_path)

    from common.scripts.run_scenario_lib import runScenario_launch

    runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    gitignore = (tmp_path / "run-scenario.inv" / ".gitignore").read_text()
    assert ".step_states/" in gitignore
    assert ".abandoned_branches/" in gitignore
    assert ".gitignore" in gitignore


# ── _sendPonytailPrimer ──────────────────────────────────────────────


def test_primeSpawnedAgent_pins_model_then_loads_ponytail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: with a model, the primer first sends "/model <id>" then "/ponytail ultra".
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1234")

    from common.scripts.run_scenario_lib import _primeSpawnedAgent

    _primeSpawnedAgent("test:main", str(signal_dir), "claude-opus-4-6[1m]")

    assert "/model claude-opus-4-6[1m]" in tracking["sent"]
    assert "/ponytail ultra" in tracking["sent"]
    # Model is pinned before the ponytail turn.
    assert tracking["sent"].index("/model claude-opus-4-6[1m]") < tracking["sent"].index("/ponytail ultra")


def test_primeSpawnedAgent_skips_model_when_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: with no model, the primer sends only "/ponytail ultra" (no /model).
    tracking = _installExecutorDoubles(monkeypatch, tmp_path)
    signal_dir = tmp_path / "signal"
    signal_dir.mkdir()
    (signal_dir / "done").write_text("1234")

    from common.scripts.run_scenario_lib import _primeSpawnedAgent

    _primeSpawnedAgent("test:main", str(signal_dir))

    assert "/ponytail ultra" in tracking["sent"]
    assert not any(s.startswith("/model") for s in tracking["sent"])


def test_splitScenarioAndModel_preserves_paths_with_spaces():
    # Scenario: --model is split off the end so a scenario path with spaces stays whole.
    from common.scripts.run_scenario_lib import _splitScenarioAndModel

    path, model = _splitScenarioAndModel(
        "/Users/x/claude code src/RevEng/scenarios/s1.txt --model claude-opus-4-6[1m]"
    )
    assert path == "/Users/x/claude code src/RevEng/scenarios/s1.txt"
    assert model == "claude-opus-4-6[1m]"

    # Without --model, the whole argument is the path and model is empty.
    path2, model2 = _splitScenarioAndModel("/Users/x/claude code src/s2.txt")
    assert path2 == "/Users/x/claude code src/s2.txt"
    assert model2 == ""


def test_launch_first_message_is_ponytail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Scenario: a freshly launched agent's first received message is "/ponytail".
    calls = _installLaunchDoubles(monkeypatch, tmp_path)

    from common.scripts.run_scenario_lib import runScenario_launch

    runScenario_launch(
        session_name="test-session",
        plugin_root=str(tmp_path / "plugin"),
        scenario_file=str(tmp_path / "scenario.txt"),
    )

    send_calls = [c for c in calls if c[0] == "send"]
    assert any("/ponytail ultra" in c[1] for c in send_calls)
