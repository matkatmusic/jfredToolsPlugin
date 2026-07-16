"""Smoke checks for scripts/jfred_tools_dispatcher.py: the silent-passthrough
contract (unmatched prompts and unknown subcommands exit 0 with empty stdout),
prompt routing for both /run-scenario and /sync-jsonl-projects, the
/jfredToolsPlugin: namespace normalization, and argv-mode subcommand routing.
Launch-path behavior needs a live tmux/Claude and is exercised by JFRED's
run-all-scenarios.py, not here."""
import json
import subprocess
import sys
from pathlib import Path

DISPATCHER = str(Path(__file__).resolve().parent.parent / "scripts" / "jfred_tools_dispatcher.py")


def runDispatcher(argv, stdin_text):
    return subprocess.run(
        [sys.executable, DISPATCHER, *argv],
        input=stdin_text, capture_output=True, text=True, timeout=30,
    )


def test_unmatched_prompt_passes_through_silently():
    # Scenario: a prompt neither command owns must pass through untouched.
    # Step: pipe an unrelated prompt payload into the dispatcher.
    payload = json.dumps({"prompt": "hello, unrelated prompt"})
    result = runDispatcher([], payload)
    # Step: silent passthrough = exit 0 with empty stdout.
    assert result.returncode == 0
    assert result.stdout == ""


def test_empty_stdin_passes_through_silently():
    # Scenario: an empty hook payload must not crash or emit output.
    result = runDispatcher([], "")
    assert result.returncode == 0
    assert result.stdout == ""


def test_unknown_subcommand_exits_zero():
    # Scenario: an argv token outside _ARGV_DISPATCH is not ours; stay silent.
    result = runDispatcher(["not-a-subcommand"], "")
    assert result.returncode == 0
    assert result.stdout == ""


def test_run_scenario_prompt_is_consumed():
    # Scenario: /run-scenario must route to runScenario_main.
    # Step: point at a scenario file that does not exist — the lib's own
    # not-found guard fires BEFORE any tmux requirement, proving the route.
    payload = json.dumps({"prompt": "/run-scenario /nonexistent/scenario.txt"})
    result = runDispatcher([], payload)
    assert result.returncode == 0
    # Step: consumption is visible as the lib's hookjson error block.
    assert "scenario file not found" in result.stdout


def test_sync_jsonl_projects_prompt_is_consumed():
    # Scenario: /sync-jsonl-projects must route to sync_main.
    # Step: pass an unknown flag — _parse_args rejects it before any file
    # I/O happens, proving the route with zero side effects.
    payload = json.dumps({"prompt": "/sync-jsonl-projects --bogus"})
    result = runDispatcher([], payload)
    assert result.returncode == 0
    assert "unrecognized argument: --bogus" in result.stdout


def test_plugin_namespaced_prompt_is_normalized():
    # Scenario: Claude Code surfaces plugin skills as /jfredToolsPlugin:<cmd>;
    # the dispatcher must strip the namespace and behave identically.
    bare = json.dumps({"prompt": "/run-scenario /nonexistent/scenario.txt"})
    namespaced = json.dumps({"prompt": "/jfredToolsPlugin:run-scenario /nonexistent/scenario.txt"})
    # Step: both payloads must produce the same consumed-route output.
    assert runDispatcher([], namespaced).stdout == runDispatcher([], bare).stdout


def test_session_start_subcommand_writes_ready_signal(tmp_path):
    # Scenario: argv-mode subcommands route to run_scenario_lib functions.
    # Step: run-scenario-session-start must create the ready signal file.
    signal_dir = tmp_path / "signals"
    result = runDispatcher(["run-scenario-session-start", str(signal_dir)], "")
    assert result.returncode == 0
    assert (signal_dir / "ready").is_file()
