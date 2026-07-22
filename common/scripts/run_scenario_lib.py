"""Hook handlers and launcher for the run-scenario skill.

The run-scenario skill drives a Claude agent in a tmux session through a
structured scenario file. This module provides the hook handlers that the
spawned agent calls (via per-invocation hooks.json) and the launcher that
sets up the tmux session.

Hook handlers:
  runScenario_sessionStart(signal_dir) — touch <signal_dir>/ready
  runScenario_stop(signal_dir)         — touch <signal_dir>/done
  runScenario_sessionEnd(signal_dir)   — write transcript_path to jsonl_path.txt
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from external.claude_plugin_lib.hookjson_lib import hookjson_checkRequirements, hookjson_emitBlock
from external.claude_plugin_lib.bg_permissions_lib import bgPermissions_loadClaude
from external.claude_plugin_lib.claude_lib import claude_buildCmd
from external.tmux_lib.tmux_lib import (
    tmux_capturePane,
    tmux_hasSession,
    tmux_killSession,
    tmux_newSession,
    tmux_sendAndSubmit,
    tmux_sendEnter,
    tmux_sendKeys,
    tmux_waitForClaudeReadiness,
)
from external.claude_plugin_lib.util_lib import terminal_spawnIfNeeded

try:
    from filelock import FileLock
except ImportError:
    from external.claude_plugin_lib.util_lib import FileLock


def runScenario_sessionStart(signal_dir: str) -> int:
    """SessionStart hook handler: create 'ready' signal file."""
    try:
        Path(signal_dir).mkdir(parents=True, exist_ok=True)
        (Path(signal_dir) / "ready").write_text(str(time.time()))
    except OSError:
        pass
    return 0


def runScenario_stop(signal_dir: str) -> int:
    """Stop hook handler: create 'done' signal file and capture transcript_path."""
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    try:
        Path(signal_dir).mkdir(parents=True, exist_ok=True)
        (Path(signal_dir) / "done").write_text(str(time.time()))
    except OSError:
        pass

    try:
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            transcript_path = data.get("transcript_path", "")
            if transcript_path:
                (Path(signal_dir) / "jsonl_path.txt").write_text(transcript_path)
    except (json.JSONDecodeError, ValueError, OSError):
        pass

    return 0


def runScenario_sessionEnd(signal_dir: str) -> int:
    """SessionEnd hook handler: capture transcript_path from stdin JSON."""
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    transcript_path = ""
    try:
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            transcript_path = data.get("transcript_path", "")
    except (json.JSONDecodeError, ValueError):
        pass

    if transcript_path:
        try:
            Path(signal_dir).mkdir(parents=True, exist_ok=True)
            (Path(signal_dir) / "jsonl_path.txt").write_text(transcript_path)
        except OSError:
            pass

    return 0


# ── Hook entry-point (UserPromptSubmit) ──────────────────────────────


def _splitScenarioAndModel(arg: str) -> tuple:
    """Split a /run-scenario argument tail into (scenario_file, model).

    An optional "--model <id>" is taken from the END so scenario paths containing
    spaces (e.g. "claude code src") stay intact. Returns model "" when none is given.
    """
    model = ""
    if " --model " in arg:
        arg, model = arg.rsplit(" --model ", 1)
    return arg.strip(), model.strip()


def runScenario_main() -> int:
    """Validate /run-scenario args, launch tmux agent, kick off executor in background.

    Blocks with an error if args are invalid. On success, launches the
    scenario as a background process and returns 0 (passthrough).
    """
    import subprocess

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        payload = {}

    prompt = (payload.get("prompt") or "") if isinstance(payload, dict) else ""
    prompt = prompt.lstrip()

    if not prompt.startswith("/run-scenario"):
        return 0

    scenario_file, model = _splitScenarioAndModel(prompt[len("/run-scenario"):].strip())

    if not scenario_file:
        print(hookjson_emitBlock(
            "run-scenario: scenario file path required.\n"
            "Usage: /run-scenario <scenario-file-path>"
        ))
        return 0

    if not Path(scenario_file).is_file():
        print(hookjson_emitBlock(
            f"run-scenario: scenario file not found: {scenario_file}"
        ))
        return 0

    hookjson_checkRequirements("run-scenario", "tmux")

    parsed = runScenario_parseScenario(scenario_file)
    if not parsed.get("steps"):
        print(hookjson_emitBlock(
            f"run-scenario: no steps found in scenario file: {scenario_file}"
        ))
        return 0

    session_name = parsed.get("session", "")
    if not session_name:
        print(hookjson_emitBlock(
            f"run-scenario: scenario file missing 'session:' header: {scenario_file}"
        ))
        return 0

    if not model:
        model = parsed.get("model", "")
    ponytail = parsed.get("ponytail", "")

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    orchestrator = f"{plugin_root}/scripts/jfred_tools_dispatcher.py"

    # Clean up previous runs of this scenario.
    src = Path(scenario_file)
    executed_dir = src.parent / "executed"
    if executed_dir.is_dir():
        for stale in executed_dir.glob(f"{src.stem}-run-*{src.suffix}"):
            stale.unlink(missing_ok=True)

    # Launch tmux agent + execute scenario in a background process.
    launch_argv = [
        "python3", orchestrator,
        "run-scenario-launch-and-execute",
        session_name, plugin_root, scenario_file,
    ]
    if model:
        launch_argv.append(model)
    else:
        launch_argv.append("")
    launch_argv.append(ponytail)
    log_file = Path(tempfile.gettempdir()) / f"run-scenario-{session_name}.log"
    log_file.write_text("")
    proc = subprocess.Popen(
        launch_argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    print(hookjson_emitBlock(
        f"[run-scenario] launching in background (pid {proc.pid})\n\n"
        f"scenario: {scenario_file}\n\n"
        f"session:  {session_name}\n\n"
        f"log: {log_file}\n\n"
        f"Look for a new Terminal window already attached to the tmux session to observe.\n\n"
        f"To force quit: kill {proc.pid}"
    ))
    return 0


# ── Launcher ─────────────────────────────────────────────────────────


def _seedWorkspaceRoot(root_dir: str) -> None:
    """Seed one workspace root with the runner support files every root needs.

    conftest.py at root and tests/ so pytest can import modules from the root
    without needing PYTHONPATH=. The .gitignore keeps runner snapshot folders
    (and itself, and the fixed-root marker) out of `git add -A` in git-baseline
    scenarios, keeping committed trees clean of runner artifacts.
    """
    conftest_content = (
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))\n"
    )
    (Path(root_dir) / "conftest.py").write_text(conftest_content)
    tests_dir = Path(root_dir) / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "conftest.py").write_text(conftest_content)
    (Path(root_dir) / ".gitignore").write_text(
        ".gitignore\n.run-scenario-root\n.step_states/\n.abandoned_branches/\n"
    )


def runScenario_createFixedRoot(root_path: str) -> str:
    """Create (or reset) one declared fixed workspace root; seed it; return its path.

    Fixed roots are created FRESH at launch and then reused across every session of
    the run. SAFETY: an existing non-empty directory is reset only when it carries the
    `.run-scenario-root` marker from a previous run — a typo'd path in a scenario
    header must never delete unrelated data.
    """
    import shutil

    root = Path(root_path).expanduser()
    marker = root / ".run-scenario-root"
    if root.exists() and not root.is_dir():
        raise ValueError(f"run-scenario: fixed root {root} exists and is not a directory")
    if root.is_dir():
        has_entries = any(root.iterdir())
        if has_entries and not marker.is_file():
            raise ValueError(
                f"run-scenario: fixed root {root} is non-empty and has no "
                f"{marker.name} marker — refusing to reset it"
            )
        shutil.rmtree(root)
    root.mkdir(parents=True)
    marker.write_text(str(time.time()))
    _seedWorkspaceRoot(str(root))
    return str(root)


def runScenario_launch(
    session_name: str,
    plugin_root: str,
    scenario_file: str,
    model: str = "",
    ponytail: str = "",
) -> dict:
    """Create tmpdir, write hooks/settings, spawn Claude in tmux, open Terminal.

    The agent runs in a fresh temp directory for isolation.
    Creates a timestamped progress copy of the scenario file.
    Returns dict with signal_dir, pane_target, progress_file, tmpdir.
    """
    from datetime import datetime
    import shutil

    # Create the working root(s) — all agent work happens in them. Declared fixed roots
    # (scenario header `root:` lines, task 169) are created fresh and reused across every
    # session of this run; the FIRST is primary (initial agent cwd + shared signal dir).
    # No declaration → a fresh random tmpdir, exactly as before.
    declared_roots = runScenario_parseScenario(scenario_file).get("roots") or []
    if declared_roots:
        tmpdir = runScenario_createFixedRoot(declared_roots[0]["path"])
        for extra_root in declared_roots[1:]:
            runScenario_createFixedRoot(extra_root["path"])
    else:
        tmpdir = tempfile.mkdtemp(prefix="run-scenario.")
        _seedWorkspaceRoot(tmpdir)
    cwd = tmpdir
    signal_dir = tmpdir

    # Create timestamped progress copy in an 'executed' subdirectory.
    src = Path(scenario_file)
    executed_dir = src.parent / "executed"
    executed_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    progress_file = executed_dir / f"{src.stem}-run-{stamp}{src.suffix}"
    # Prepend the tmpdir path to the progress copy so the user knows where files are.
    scenario_content = src.read_text()
    progress_file.write_text(f"tmpdir: {tmpdir}\n{scenario_content}")

    # Clean up previous tmpdir for THIS scenario only.
    # Read the executed file we're about to overwrite to find its old tmpdir.
    if executed_dir.is_dir():
        for old_exec in executed_dir.glob(f"{src.stem}-run-*{src.suffix}"):
            old_text = old_exec.read_text()
            for old_line in old_text.splitlines():
                if old_line.startswith("tmpdir: "):
                    old_tmpdir = Path(old_line[len("tmpdir: "):])
                    if old_tmpdir.is_dir():
                        if old_tmpdir != Path(tmpdir):
                            shutil.rmtree(old_tmpdir, ignore_errors=True)
                    break

    orchestrator_path = f"{plugin_root}/scripts/jfred_tools_dispatcher.py"

    # Write the compound-command blocker as a script so escaping isn't an issue.
    block_script = Path(tmpdir) / "block-compound.sh"
    block_script.write_text(
        "#!/bin/bash\n"
        "jq -r '.tool_input.command' | grep -qE '(&&|\\|\\||;)' "
        "&& echo 'No compound commands — issue separately' >&2 && exit 2 "
        "|| exit 0\n"
    )
    block_script.chmod(0o755)

    hook_log = str(Path(tempfile.gettempdir()) / f"run-scenario-{session_name}-hooks.log")
    log_cmd = f"echo \"$(date +%s.%N) $CLAUDE_HOOK_EVENT_NAME\" >> '{hook_log}'"
    hook_logger = {"type": "command", "command": f"bash -c '{log_cmd}'"}
    hooks_data = {
        "SessionStart": [{"hooks": [hook_logger, {"type": "command", "command": f"python3 {orchestrator_path} run-scenario-session-start '{signal_dir}'"}]}],
        "Stop": [{"hooks": [hook_logger, {"type": "command", "command": f"python3 {orchestrator_path} run-scenario-stop '{signal_dir}'"}]}],
        "SessionEnd": [{"hooks": [hook_logger, {"type": "command", "command": f"python3 {orchestrator_path} run-scenario-session-end '{signal_dir}'"}]}],
        "Notification": [{"hooks": [hook_logger]}],
        "PreToolUse": [{"hooks": [hook_logger]}, {"matcher": "Bash", "hooks": [{"type": "command", "command": str(block_script)}]}],
        "PostToolUse": [{"hooks": [hook_logger]}],
        "UserPromptSubmit": [{"hooks": [hook_logger]}],
    }
    hooks_json_file = Path(tmpdir) / "hooks.json"
    hooks_json_file.write_text(json.dumps(hooks_data))

    allow_json = bgPermissions_loadClaude(
        "run_scenario",
        env={"CWD": cwd, "HOME": str(Path.home()), "REPO_ROOT": cwd},
    )

    settings_file = Path(tmpdir) / "settings.json"
    claude_cmd = claude_buildCmd(
        str(settings_file), allow_json, str(hooks_json_file), cwd,
    ).strip()
    if model:
        claude_cmd += f" --model '{model}'"

    pane_target = f"{session_name}:main"
    tmux_newSession(session_name, "-n", "main", "-c", cwd, claude_cmd)

    # Dismiss folder trust prompt if present.
    for _ in range(10):
        content = tmux_capturePane(pane_target, 20)
        if "trust this folder" in content:
            tmux_sendEnter(pane_target)
            break
        time.sleep(1)

    terminal_spawnIfNeeded(session_name, maximize="tall")

    # Wait for SessionStart hook to fire (proves Claude is live).
    _waitForSignalFile(signal_dir, "ready", timeout=60)

    # Wait for the TUI input field to be ready (❯ glyph visible).
    tmux_waitForClaudeReadiness(pane_target, timeout=60)

    _primeSpawnedAgent(pane_target, signal_dir, ponytail)

    return {
        "signal_dir": signal_dir,
        "pane_target": pane_target,
        "progress_file": str(progress_file),
        "tmpdir": tmpdir,
    }


# ── Parser ───────────────────────────────────────────────────────────

# Group 1 = action keyword, group 2 = optional "@agentName" target, group 3 = payload.
_STEP_RE = re.compile(
    r"^-\s*\[[ x]\]\s*\d+\.\s*"
    r"(SayQueued|Say|Edit|Rewind|Exit|Record|Wait|EndCurrentAgentAndSpawnNewAgent|SpawnNewAgent)"
    r"\b(?:\s*@(\w+))?[:\s]*(.*)",
    re.IGNORECASE,
)
_SLASH_CMD_RE = re.compile(
    r"^-\s*\[[ x]\]\s*\d+\.\s*/(compact|clear)\s*$",
    re.IGNORECASE,
)
_BACKTICK_RE = re.compile(r"`([^`]+)`")

# Verbose scenario directives mapped to their internal action name.
_ACTION_ALIASES = {
    "endcurrentagentandspawnnewagent": "spawn",
    "spawnnewagent": "spawnconcurrent",
}

# Trailing `in <rootName>` on a spawn payload selects a declared workspace root (task 169).
_SPAWN_ROOT_RE = re.compile(r"^(.*?)\s*\bin\s+(\w+)\s*$", re.IGNORECASE)


def runScenario_splitSpawnRoot(payload: str) -> tuple:
    """Split a spawn payload into (payload_without_root, root_name_or_None)."""
    m = _SPAWN_ROOT_RE.match(payload.strip())
    if not m:
        return payload.strip(), None
    return m.group(1).strip(), m.group(2).lower()


def runScenario_convertTxtToJson(txt_path: str) -> dict:
    """Convert a .txt scenario file to a JSON-serializable dict."""
    text = Path(txt_path).read_text()
    parts = text.split("---", 1)

    session = ""
    model = ""
    ponytail = ""
    roots = []
    if len(parts) >= 1:
        for line in parts[0].splitlines():
            stripped = line.strip()
            low = stripped.lower()
            if low.startswith("session:"):
                session = stripped[len("session:"):].strip()
            elif low.startswith("model:"):
                model = stripped[len("model:"):].strip()
            elif low.startswith("ponytail:"):
                ponytail = stripped[len("ponytail:"):].strip()
            elif low.startswith("root:"):
                # Named fixed workspace root: `root: <name> = <path>` (task 169). The FIRST
                # declared root is primary (initial agent cwd + shared signal dir).
                root_decl = stripped[len("root:"):].strip()
                if "=" in root_decl:
                    root_name, root_path = root_decl.split("=", 1)
                    roots.append({"name": root_name.strip().lower(), "path": root_path.strip()})

    steps = []
    body = parts[1] if len(parts) > 1 else parts[0]
    step_num = 0
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ["):
            continue

        step_num += 1

        sm = _SLASH_CMD_RE.match(stripped)
        if sm:
            steps.append({
                "action": sm.group(1).lower(),
                "payload": "",
                "target": None,
                "step_num": step_num,
            })
            continue

        m = _STEP_RE.match(stripped)
        if not m:
            steps.append({
                "action": "unknown",
                "payload": stripped,
                "target": None,
                "step_num": step_num,
            })
            continue

        action = m.group(1).lower()
        action = _ACTION_ALIASES.get(action, action)
        agent_target = (m.group(2) or "").lower() or None
        payload_raw = m.group(3).strip()

        if action in ("say", "sayqueued"):
            bt = _BACKTICK_RE.search(payload_raw)
            payload = bt.group(1) if bt else payload_raw
        else:
            payload = payload_raw

        # Spawn steps may pick a declared root with a trailing `in <name>` (task 169);
        # strip it here so payload semantics (agent name, --excludeJSONL) stay clean.
        step_root = None
        if action in ("spawn", "spawnconcurrent"):
            payload, step_root = runScenario_splitSpawnRoot(payload)

        steps.append({
            "action": action,
            "payload": payload,
            "target": agent_target,
            "step_num": step_num,
            "root": step_root,
        })

    return {"session": session, "model": model, "ponytail": ponytail, "roots": roots, "steps": steps}


def runScenario_saveTxtAsJson(txt_path: str) -> str:
    """Convert a .txt scenario to .json and write it to disk. Returns the .json path."""
    data = runScenario_convertTxtToJson(txt_path)
    json_path = str(Path(txt_path).with_suffix(".json"))
    Path(json_path).write_text(json.dumps(data, indent=2))
    return json_path


def runScenario_loadJson(json_path: str) -> dict:
    """Load a .json scenario file."""
    return json.loads(Path(json_path).read_text())


def runScenario_parseScenario(scenario_path: str) -> dict:
    """Load a scenario from .txt or .json. Converts .txt to JSON on the fly."""
    p = Path(scenario_path)
    if p.suffix == ".json":
        return runScenario_loadJson(scenario_path)
    return runScenario_convertTxtToJson(scenario_path)


# ── Executor ─────────────────────────────────────────────────────────

SIGNAL_POLL_INTERVAL_S = 1
SIGNAL_POLL_TIMEOUT_S = 300

_PANE_TARGET_FOR_DISMISS = ""


def _dismissPermissionPrompt(pane_target: str) -> None:
    """If the pane is showing a Read permission dialog, approve it."""
    if not pane_target:
        return
    content = tmux_capturePane(pane_target, 20)
    if "Do you want to proceed?" in content:
        if "Read(" in content:
            tmux_sendEnter(pane_target)


def _waitForSignalFile(signal_dir: str, filename: str, timeout: float = SIGNAL_POLL_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    target = Path(signal_dir) / filename
    while time.time() < deadline:
        if target.is_file():
            return True
        _dismissPermissionPrompt(_PANE_TARGET_FOR_DISMISS)
        time.sleep(SIGNAL_POLL_INTERVAL_S)
    return False


def _clearSignalFile(signal_dir: str, filename: str) -> None:
    target = Path(signal_dir) / filename
    if target.is_file():
        target.unlink()


def _markCheckbox(progress_file: str, step_num: int) -> None:
    path = Path(progress_file)
    if not path.is_file():
        return
    content = path.read_text()
    pattern = re.compile(rf"^(- \[ \] {step_num}\.)", re.MULTILINE)
    content = pattern.sub(f"- [x] {step_num}.", content)
    path.write_text(content)


def _executeSay(pane_target: str, signal_dir: str, payload: str) -> bool:
    _clearSignalFile(signal_dir, "done")
    tmux_sendAndSubmit(pane_target, payload)
    return _waitForSignalFile(signal_dir, "done")


_REWIND_RE = re.compile(r"^(\d+)(?:\s*,\s*code)?$", re.IGNORECASE)


def _executeRewind(pane_target: str, payload: str) -> None:
    """Execute /rewind with N up presses and menu selection.

    Payload format: "N" (conversation only) or "N, code" (restore code).
    Menu items when code was changed: 1=code+conversation, 2=conversation only.
    Menu items when no code changed: 1=conversation only (no code option).
    We send "1" for code restoration, "2" for conversation only.
    If no code was changed, "1" is already conversation only.
    """
    m = _REWIND_RE.match(payload.strip())
    if not m:
        raise ValueError(f"unrecognized rewind payload: {payload}")

    up_count = int(m.group(1))
    restore_code = ", code" in payload.lower()

    tmux_sendAndSubmit(pane_target, "/rewind")
    time.sleep(3)

    for _ in range(up_count):
        tmux_sendKeys(pane_target, "Up")
        time.sleep(0.3)

    tmux_sendEnter(pane_target)
    time.sleep(3)

    # Menu depends on whether code changed at the rewind point:
    #   Code changed:    1=code+conversation, 2=conversation, 3=code, 4=summarize...
    #   No code changed: 1=conversation, 2=summarize...
    # Capture pane to detect which menu is showing.
    time.sleep(3)
    menu_content = tmux_capturePane(pane_target, 20)
    has_code_option = "Restore code and conversation" in menu_content

    if restore_code:
        tmux_sendKeys(pane_target, "1")
    elif has_code_option:
        tmux_sendKeys(pane_target, "2")
    else:
        tmux_sendKeys(pane_target, "1")
    time.sleep(1)

    tmux_waitForClaudeReadiness(pane_target, 30)
    time.sleep(2)
    tmux_sendKeys(pane_target, "C-u")
    time.sleep(1)
    tmux_sendKeys(pane_target, "C-u")
    time.sleep(0.5)


# Runner-injected / signal files excluded from on-disk snapshots.
# `.step_states` and `.gitignore` keep a snapshot from recursively capturing prior
# snapshots or the runner-injected gitignore.
_SNAPSHOT_EXCLUDE = {
    ".git", ".abandoned_branches", ".step_states", ".gitignore",
    ".run-scenario-root",
    "hooks.json", "settings.json",
    "block-compound.sh", "conftest.py", "ready", "done", "jsonl_path.txt",
}


def _copyWorkingTree(cwd: str, dest: str) -> list:
    """Copy cwd's top-level entries into dest, skipping runner/signal/snapshot files.

    Recurses into subdirectories but drops conftest.py and __pycache__. Returns the
    sorted list of copied top-level names.
    """
    import shutil

    root = Path(cwd)
    captured = []
    for entry in root.iterdir():
        if entry.name in _SNAPSHOT_EXCLUDE:
            continue
        if entry.is_dir():
            shutil.copytree(entry, Path(dest) / entry.name,
                            ignore=shutil.ignore_patterns("conftest.py", "__pycache__"))
        else:
            shutil.copy2(entry, Path(dest) / entry.name)
        captured.append(entry.name)
    return sorted(captured)


def _workingTreeSignature(cwd: str) -> dict:
    """Map each working-tree file (relative path) to a hash of its contents.

    Honors _SNAPSHOT_EXCLUDE (and the same conftest.py/__pycache__ drops as
    _copyWorkingTree) so runner/signal/snapshot files never register as a change.
    Used to capture a step only when it actually changed code.
    """
    import hashlib

    root = Path(cwd)
    signature = {}
    for entry in root.iterdir():
        if entry.name in _SNAPSHOT_EXCLUDE:
            continue
        if entry.is_dir():
            for found in entry.rglob("*"):
                if not found.is_file():
                    continue
                if "__pycache__" in found.parts or found.name == "conftest.py":
                    continue
                signature[str(found.relative_to(root))] = hashlib.sha1(found.read_bytes()).hexdigest()
        elif entry.is_file():
            signature[entry.name] = hashlib.sha1(entry.read_bytes()).hexdigest()
    return signature


def _snapshotAbandonedBranch(cwd: str, index: int, step_num: int, payload: str,
                             staging_dir: str = "") -> str:
    """Copy the current working files into .abandoned_branches/abandoned-branch-<index>/.

    Captures the file state a rewind is about to abandon, so a downstream engine can
    extract and compare branches. Skips runner/signal files and writes a manifest.json.
    Returns the snapshot directory path.
    """
    import shutil

    root = Path(staging_dir) if staging_dir else Path(cwd)
    dest = root / ".abandoned_branches" / f"abandoned-branch-{index}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    captured = _copyWorkingTree(cwd, str(dest))

    manifest = {
        "label": f"abandoned-branch-{index}",
        "step_num": step_num,
        "rewind": payload,
        "code_rewind": ", code" in payload.lower(),
        "files": captured,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return str(dest)


def _snapshotStep(cwd: str, step_num: int, action: str, payload: str,
                  staging_dir: str = "") -> str:
    """Copy the working tree after a step into .step_states/step-<NNN>/ with a manifest.

    Gives a downstream reconstruction engine the real on-disk state to diff against at
    every step (post-edit state included). Skips runner/signal/snapshot files. Returns
    the snapshot directory path.
    """
    import shutil

    label = f"step-{step_num:03d}"
    root = Path(staging_dir) if staging_dir else Path(cwd)
    dest = root / ".step_states" / label
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    captured = _copyWorkingTree(cwd, str(dest))

    manifest = {
        "label": label,
        "step_num": step_num,
        "action": action,
        "payload": payload,
        "files": captured,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return str(dest)


def _moveStagedSnapshots(staging_dir: str, cwd: str) -> None:
    """Move .step_states/ and .abandoned_branches/ from staging into the working tree."""
    import shutil
    if not staging_dir or not cwd:
        return
    staging = Path(staging_dir)
    dest = Path(cwd)
    for name in (".step_states", ".abandoned_branches"):
        src = staging / name
        if src.is_dir():
            target = dest / name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(src), str(target))
    shutil.rmtree(staging_dir, ignore_errors=True)


_EDIT_PREPEND_RE = re.compile(r"^(.+?)\s*—\s*prepend\s+`([^`]+)`", re.IGNORECASE)
_EDIT_APPEND_RE = re.compile(r"^(.+?)\s*—\s*append\s+`([^`]+)`", re.IGNORECASE)
_EDIT_AFTER_RE = re.compile(r"^(.+?)\s*—\s*after\s+`([^`]+)`\s+insert\s+`([^`]+)`", re.IGNORECASE)
_EDIT_BEFORE_RE = re.compile(r"^(.+?)\s*—\s*before\s+`([^`]+)`\s+insert\s+`([^`]+)`", re.IGNORECASE)


def _executeEdit(cwd: str, payload: str) -> None:
    """Mechanically insert a comment into a file based on structured payload."""
    m = _EDIT_PREPEND_RE.match(payload)
    if m:
        target = Path(cwd) / m.group(1).strip()
        comment = m.group(2)
        target.write_text(comment + "\n" + target.read_text())
        return

    m = _EDIT_APPEND_RE.match(payload)
    if m:
        target = Path(cwd) / m.group(1).strip()
        comment = m.group(2)
        text = target.read_text()
        if not text.endswith("\n"):
            text += "\n"
        target.write_text(text + comment + "\n")
        return

    m = _EDIT_AFTER_RE.match(payload)
    if m:
        target = Path(cwd) / m.group(1).strip()
        marker = m.group(2)
        comment = m.group(3)
        lines = target.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            if marker in line:
                lines.insert(i + 1, comment + "\n")
                break
        target.write_text("".join(lines))
        return

    m = _EDIT_BEFORE_RE.match(payload)
    if m:
        target = Path(cwd) / m.group(1).strip()
        marker = m.group(2)
        comment = m.group(3)
        lines = target.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            if marker in line:
                lines.insert(i, comment + "\n")
                break
        target.write_text("".join(lines))
        return

    raise ValueError(f"unrecognized edit payload: {payload}")


# Compaction can take a while on a large conversation; wait generously for the hook.
COMPACT_DONE_TIMEOUT_S = 180

# ponytail: timing knob — too low queues before the tool call starts (degenerates to a
# sequential Say); too high and the turn may already be over. Tune per model/hardware.
SAYQUEUED_DELAY_S = 2


def _executeCompact(signal_dir: str, pane_target: str) -> None:
    """Send /compact and block until compaction actually finishes.

    Compaction emits a SessionStart hook (source "compact") on completion, which
    re-touches `ready`. Clearing the existing `ready` first, then waiting for it to
    reappear, is the only reliable "compaction done" signal — a readiness glyph can
    show before the summary is built, which would let the next message race in
    mid-compact.
    """
    _clearSignalFile(signal_dir, "ready")
    tmux_sendAndSubmit(pane_target, "/compact")
    _waitForSignalFile(signal_dir, "ready", timeout=COMPACT_DONE_TIMEOUT_S)
    tmux_waitForClaudeReadiness(pane_target, 60)
    time.sleep(2)


def _executeClear(signal_dir: str, pane_target: str) -> None:
    """Send /clear and block until the context reset finishes.

    Like /compact, /clear emits a SessionStart hook (source "clear") on completion
    that re-touches `ready`; gate on that rather than on a readiness glyph.
    """
    _clearSignalFile(signal_dir, "ready")
    tmux_sendAndSubmit(pane_target, "/clear")
    _waitForSignalFile(signal_dir, "ready", timeout=COMPACT_DONE_TIMEOUT_S)
    tmux_waitForClaudeReadiness(pane_target, 30)
    time.sleep(2)


def _executeExit(pane_target: str) -> None:
    tmux_sendAndSubmit(pane_target, "/exit")


def _executeRecord(signal_dir: str) -> str:
    path_file = Path(signal_dir) / "jsonl_path.txt"
    if path_file.is_file():
        return path_file.read_text().strip()
    return ""


def _primeSpawnedAgent(pane_target: str, signal_dir: str, ponytail: str = "") -> None:
    """Prime a freshly-spawned agent: load the ponytail skill.

    Model is set via --model on the claude launch command, not here.
    /ponytail produces a turn, so we clear `done` and block on it (mirrors _executeSay).
    """
    level = ponytail or "ultra"
    _log = Path(tempfile.gettempdir()) / f"run-scenario-{pane_target.split(':')[0]}.log"
    def _mark(msg: str) -> None:
        with open(_log, "a") as fh:
            fh.write(f"[{time.time():.1f}] _prime: {msg}\n")
            fh.flush()
    if level == "none":
        _mark("ponytail: none — skipping /ponytail")
        return
    _mark("clearing done signal")
    _clearSignalFile(signal_dir, "done")
    _mark(f"sending /ponytail {level}")
    tmux_sendAndSubmit(pane_target, f"/ponytail {level}")
    _mark(f"/ponytail {level} sent, waiting for done")
    _waitForSignalFile(signal_dir, "done")
    _mark("done signal received")


def _spawnClaudeInTmux(session_name: str, cwd: str, settings_file: str, model: str = "", ponytail: str = "", signal_dir: str = "") -> str:
    """Start a fresh Claude tmux session in cwd reusing the on-disk settings; return pane_target.

    signal_dir: where the generated hooks touch ready/done — defaults to cwd, but an agent
    spawned into a secondary fixed root (task 169) still signals the PRIMARY root's dir.
    """
    effective_signal_dir = signal_dir or cwd
    claude_cmd = f"claude --settings '{settings_file}' --add-dir '{cwd}'"
    if model:
        claude_cmd += f" --model '{model}'"
    pane_target = f"{session_name}:main"
    tmux_newSession(session_name, "-n", "main", "-c", cwd, claude_cmd)
    for _ in range(10):
        if "trust this folder" in tmux_capturePane(pane_target, 20):
            tmux_sendEnter(pane_target)
            break
        time.sleep(1)
    terminal_spawnIfNeeded(session_name, maximize="tall")
    _waitForSignalFile(effective_signal_dir, "ready", timeout=60)
    tmux_waitForClaudeReadiness(pane_target, timeout=30)
    _primeSpawnedAgent(pane_target, effective_signal_dir, ponytail)
    return pane_target


def _executeSpawn(signal_dir: str, pane_target: str, cwd: str,
                  session_name: str, agent_index: int, payload: str,
                  captured: list, model: str = "", ponytail: str = "",
                  settings_file: str = "") -> str:
    """End the current agent (optionally dropping its JSONL), then launch a fresh agent in the tmpdir.

    The previous agent is torn down deterministically — /exit, wait for its tmux
    session to disappear, then hard-kill to be certain — BEFORE the next agent starts,
    so the two never run concurrently. Its transcript is already on disk (the Stop hook
    recorded it), and the tmpdir + committed repo persist. Returns the new pane_target.
    """
    prev = _executeRecord(signal_dir)
    if prev and "--excludejsonl" not in payload.lower() and prev not in captured:
        captured.append(prev)
    old_session = pane_target.split(":")[0]
    _executeExit(pane_target)
    for _ in range(10):
        if tmux_hasSession(old_session) != 0:
            break
        time.sleep(1)
    tmux_killSession(old_session)
    for name in ("ready", "done", "jsonl_path.txt"):
        _clearSignalFile(signal_dir, name)
    settings = settings_file or str(Path(cwd) / "settings.json")
    return _spawnClaudeInTmux(f"{session_name}-a{agent_index}", cwd, settings, model, ponytail, signal_dir=signal_dir)


def _executeSpawnConcurrent(signal_dir: str, cwd: str, session_name: str,
                            agent_index: int, model: str = "", ponytail: str = "",
                            settings_file: str = "") -> str:
    """Launch an additional Claude agent in its own tmux session without ending
    any existing agent. Returns the new agent's pane_target.

    ponytail: the shared signal_dir is safe ONLY because the executor prompts one
    agent at a time and waits for `done`; true-parallel prompting would need a
    per-agent signal_dir + Stop/SessionEnd hook rework.
    """
    # Clear the readiness/turn signals so we can wait for the NEW agent's
    # SessionStart. Do NOT clear jsonl_path.txt and do NOT /exit or kill the
    # current agent — both agents stay alive.
    for signal_name in ("ready", "done"):
        _clearSignalFile(signal_dir, signal_name)
    settings = settings_file or str(Path(cwd) / "settings.json")
    return _spawnClaudeInTmux(
        f"{session_name}-a{agent_index}", cwd, settings, model, ponytail, signal_dir=signal_dir
    )


def _resolveSpawnRoot(step: dict, roots_by_name: dict, default_cwd: str) -> str:
    """The working dir for a spawn step: its declared root, or default_cwd without one.

    An undeclared root name fails loudly — a silent fallback would run the session in
    the wrong directory and poison the scenario's captures.
    """
    root_name = step.get("root")
    if not root_name:
        return default_cwd
    if root_name not in roots_by_name:
        raise ValueError(
            f"run-scenario: step {step.get('step_num')} spawns into undeclared root '{root_name}'"
        )
    return roots_by_name[root_name]


def runScenario_executeSteps(
    signal_dir: str,
    pane_target: str,
    progress_file: str,
    steps: list,
    start_from: int = 0,
    cwd: str = "",
    session_name: str = "",
    model: str = "",
    ponytail: str = "",
    roots: list = None,
) -> dict:
    """Execute scenario steps automatically.

    Returns:
        {"completed": True, "jsonl_path": "..."} when all steps finish.
        {"completed": False, "paused_at": N, "action": "unknown", ...} on unrecognized steps.
    """
    global _PANE_TARGET_FOR_DISMISS
    _PANE_TARGET_FOR_DISMISS = pane_target
    base_session = session_name or pane_target.split(":")[0]
    _log = Path(tempfile.gettempdir()) / f"run-scenario-{base_session}.log"
    def _mark(msg: str) -> None:
        with open(_log, "a") as fh:
            fh.write(f"[{time.time():.1f}] {msg}\n")
            fh.flush()
    jsonl_path = ""
    captured = []
    abandoned = []
    step_states = []
    agent_index = 1
    abandoned_index = 0
    agent_panes_by_name = {"a1": pane_target}
    active_agent_name = "a1"
    agent_jsonl_by_name = {}
    # Named fixed workspace roots (task 169): spawn steps may place an agent in one; every
    # agent's cwd is tracked so Edit steps land in the ACTIVE agent's root. All agents share
    # the primary root's settings.json and signal_dir.
    roots_by_name = {}
    for declared_root in (roots or []):
        roots_by_name[declared_root["name"]] = str(Path(declared_root["path"]).expanduser())
    agent_cwd_by_name = {"a1": cwd}
    primary_settings = str(Path(cwd) / "settings.json") if cwd else ""
    # Stage snapshots outside the working tree so scenario code that walks
    # the directory (e.g. os.walk) can't corrupt earlier captures.
    snapshot_staging = tempfile.mkdtemp(prefix="step-states.") if cwd else ""

    for i in range(start_from, len(steps)):
        step = steps[i]
        action = step["action"]
        payload = step["payload"]
        step_num = step["step_num"]

        target_agent_name = step.get("target") or active_agent_name
        current_pane = agent_panes_by_name.get(target_agent_name, pane_target)
        current_cwd = agent_cwd_by_name.get(target_agent_name, cwd)
        active_agent_name = target_agent_name
        _PANE_TARGET_FOR_DISMISS = current_pane

        t0 = time.time()
        _mark(f"step {step_num} [{action}] sending — {payload[:80]}")

        if action == "say":
            next_is_queued = i + 1 < len(steps) and steps[i + 1]["action"] == "sayqueued"
            if next_is_queued:
                # Send without blocking so the follow-on SayQueued lands mid-turn.
                _clearSignalFile(signal_dir, "done")
                tmux_sendAndSubmit(current_pane, payload)
            else:
                _executeSay(current_pane, signal_dir, payload)
                agent_jsonl_by_name[target_agent_name] = _executeRecord(signal_dir)
            _markCheckbox(progress_file, step_num)

        elif action == "sayqueued":
            time.sleep(SAYQUEUED_DELAY_S)
            tmux_sendAndSubmit(current_pane, payload)   # queues onto the in-flight turn
            _waitForSignalFile(signal_dir, "done")
            agent_jsonl_by_name[target_agent_name] = _executeRecord(signal_dir)
            _markCheckbox(progress_file, step_num)

        elif action == "wait":
            _waitForSignalFile(signal_dir, "done")
            _markCheckbox(progress_file, step_num)

        elif action == "rewind":
            if cwd:
                abandoned_index += 1
                _snapshotAbandonedBranch(cwd, abandoned_index, step_num, payload, snapshot_staging)
                abandoned.append(f"abandoned-branch-{abandoned_index}")
            _executeRewind(current_pane, payload)
            _markCheckbox(progress_file, step_num)

        elif action == "spawn":
            agent_index += 1
            spawn_cwd = _resolveSpawnRoot(step, roots_by_name, cwd)
            new_pane = _executeSpawn(
                signal_dir, current_pane, spawn_cwd, base_session, agent_index, payload, captured, model, ponytail,
                settings_file=primary_settings,
            )
            agent_panes_by_name[active_agent_name] = new_pane
            agent_cwd_by_name[active_agent_name] = spawn_cwd
            pane_target = new_pane
            _PANE_TARGET_FOR_DISMISS = new_pane
            _markCheckbox(progress_file, step_num)

        elif action == "spawnconcurrent":
            agent_index += 1
            new_agent_name = payload.strip() or f"a{agent_index}"
            spawn_cwd = _resolveSpawnRoot(step, roots_by_name, cwd)
            agent_panes_by_name[new_agent_name] = _executeSpawnConcurrent(
                signal_dir, spawn_cwd, base_session, agent_index, model, ponytail,
                settings_file=primary_settings,
            )
            agent_cwd_by_name[new_agent_name] = spawn_cwd
            active_agent_name = new_agent_name
            _PANE_TARGET_FOR_DISMISS = agent_panes_by_name[new_agent_name]
            _markCheckbox(progress_file, step_num)

        elif action == "exit":
            _executeExit(current_pane)
            _markCheckbox(progress_file, step_num)

        elif action == "record":
            if step.get("target"):
                jsonl_path = agent_jsonl_by_name.get(target_agent_name, "") or _executeRecord(signal_dir)
            else:
                jsonl_path = _executeRecord(signal_dir)
            if jsonl_path and jsonl_path not in captured:
                captured.append(jsonl_path)
            _markCheckbox(progress_file, step_num)

        elif action == "edit":
            _executeEdit(current_cwd, payload)
            _markCheckbox(progress_file, step_num)

        elif action == "compact":
            _executeCompact(signal_dir, current_pane)
            _markCheckbox(progress_file, step_num)

        elif action == "clear":
            _executeClear(signal_dir, current_pane)
            _markCheckbox(progress_file, step_num)

        else:
            _mark(f"step {step_num} UNKNOWN action={action}")
            return {
                "completed": False,
                "paused_at": i,
                "action": "unknown",
                "payload": payload,
                "step_num": step_num,
            }

        _mark(f"step {step_num} [{action}] done — {time.time() - t0:.1f}s")

        # Capture on-disk state after every step — gives the engine a complete
        # timeline and makes audit a simple count comparison.
        # ponytail: snapshots capture the PRIMARY root only; extend to per-root captures
        # when a multi-root scenario needs them (task 177).
        if cwd:
            _snapshotStep(cwd, step_num, action, payload, snapshot_staging)
            step_states.append(f"step-{step_num:03d}")

    # Move staged snapshots into the working tree now that the agent is done.
    _moveStagedSnapshots(snapshot_staging, cwd)

    # Tear down any agents still alive so re-running this scenario does not collide
    # on tmux session names. Best-effort: only kill sessions that still exist.
    for agent_pane in agent_panes_by_name.values():
        agent_session_name = agent_pane.split(":")[0]
        if tmux_hasSession(agent_session_name) == 0:
            tmux_killSession(agent_session_name)

    return {
        "completed": True,
        "jsonl_path": jsonl_path,
        "jsonl_paths": captured,
        "abandoned_branches": abandoned,
        "step_states": step_states,
    }


def runScenario_launchAndExecute(
    session_name: str,
    plugin_root: str,
    scenario_file: str,
    model: str = "",
    ponytail: str = "",
) -> int:
    """Combined entry-point: launch tmux agent, then execute all scenario steps."""
    _log = Path(tempfile.gettempdir()) / f"run-scenario-{session_name}.log"
    def _mark(msg: str) -> None:
        with open(_log, "a") as fh:
            fh.write(f"[{time.time():.1f}] {msg}\n")
            fh.flush()
    _mark(f"START pid={os.getpid()} session={session_name}")
    try:
        parsed = runScenario_parseScenario(scenario_file)
        if not model:
            model = parsed.get("model", "")
        if not ponytail:
            ponytail = parsed.get("ponytail", "")
        _mark("parsed scenario")
        launch_result = runScenario_launch(session_name, plugin_root, scenario_file, model, ponytail)
        _mark(f"launch returned: {type(launch_result).__name__}")
        if not isinstance(launch_result, dict):
            _mark("launch failed — not a dict")
            return 1

        _mark("starting executeSteps")
        progress_file = launch_result["progress_file"]
        result = runScenario_executeSteps(
            launch_result["signal_dir"],
            launch_result["pane_target"],
            progress_file,
            parsed["steps"],
            cwd=launch_result["tmpdir"],
            session_name=session_name,
            model=model,
            ponytail=ponytail,
            roots=parsed.get("roots"),
        )
        _mark(f"executeSteps done: {json.dumps(result)}")

        with open(progress_file, "a") as fh:
            fh.write(f"\n---\nresult: {json.dumps(result)}\n")
        _mark("DONE")
    except Exception as exc:
        import traceback
        _mark(f"EXCEPTION: {exc}\n{traceback.format_exc()}")
        raise

    return 0


def runScenario_execute(
    signal_dir: str,
    pane_target: str,
    scenario_file: str,
    progress_file: str,
    start_from: str = "0",
) -> int:
    """Argv-callable wrapper: parse scenario, execute steps, print JSON result.

    When paused on an edit, includes the exact resume command in the output
    so the agent knows how to continue after performing the edit.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    orchestrator = f"{plugin_root}/scripts/jfred_tools_dispatcher.py"

    parsed = runScenario_parseScenario(scenario_file)
    result = runScenario_executeSteps(
        signal_dir, pane_target, progress_file,
        parsed["steps"], int(start_from),
        cwd=parsed.get("cwd", ""),
        roots=parsed.get("roots"),
    )

    if not result["completed"]:
        resume_from = result["paused_at"] + 1
        result["resume_command"] = (
            f"python3 {orchestrator} run-scenario-execute "
            f"'{signal_dir}' '{pane_target}' '{scenario_file}' '{progress_file}' '{resume_from}'"
        )

    print(json.dumps(result))
    return 0
