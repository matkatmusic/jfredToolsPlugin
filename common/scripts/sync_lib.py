"""Handler for the `/sync-jsonl-projects` do-nothing Jot skill.

Backs up Claude Code session data (`.jsonl` files, subagents, tool-results) and
file-history snapshots from `~/.claude/projects/` and `~/.claude/file-history/`
to a local `.claude-data/` backup, using rsync. Supports four modes plus a
`--dry-run` modifier:

    /sync-jsonl-projects               -> sync CWD's sessions   -> <CWD>/.claude-data/
    /sync-jsonl-projects --only <path> -> sync a repo's sessions-> <path>/.claude-data/
    /sync-jsonl-projects --only <file> -> repos listed in file  -> archive at the CWD
    /sync-jsonl-projects --all  <dest> -> everything            -> <dest>/
    /sync-jsonl-projects --undo        -> reverse the last sync

Output is surfaced via `hookjson_emitBlock`; the itemized change list is written
to `<dest>/.sync-logs/` for durable history and undo.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from external.claude_plugin_lib.hookjson_lib import hookjson_checkRequirements, hookjson_emitBlock
from external.claude_plugin_lib.util_lib import _util_resolvePluginRoot
from common.scripts.sync_lib_paths import (
    _derive_project_dir,
    _ensure_gitignore,
    _file_history_root,
    _parse_args,
    _projects_root,
    _read_repo_list,
    _resolve_session_uuids,
    _timestamp,
)
from common.scripts.sync_lib_rsync import (
    _RETENTION,
    _classify_line,
    _clear_pointer,
    _delete_file,
    _is_new_file,
    _parse_log,
    _prune_old_logs,
    _read_pointer,
    _remove_log_pair,
    _restore_file,
    _rsync_job,
    _write_log,
    _write_pointer,
)
from common.scripts.sync_lib_format import (
    _assemble_summary,
    _format_group,
    _format_undo_group,
)


def _build_jobs(mode: str, arg: str | None, payload_cwd: str) -> tuple[list[tuple], str | None]:
    """Resolve a mode into [(dest_root, [(label, src, dest), ...]), ...] + error.
    `label` is the dest path relative to dest_root, e.g. `projects/<encoded>`."""
    if mode == "all":
        return _build_all_jobs(arg)
    if mode == "only" and arg and not os.path.isabs(arg):
        arg = str(Path(payload_cwd) / arg)  # resolve relative to where it was run
    if mode == "only" and _is_list_file(arg):
        return _build_list_jobs(Path(arg), payload_cwd)

    repos, error = _resolve_repos(mode, arg, payload_cwd)
    if error:
        return [], error

    groups = [g for g in (_build_repo_group(r) for r in repos) if g is not None]
    if not groups:
        return [], "no recorded sessions found for the target directory"
    return groups, None


def _build_all_jobs(arg: str | None) -> tuple[list[tuple], str | None]:
    if not arg:
        return [], "--all requires a destination path"
    dest_root = Path(arg).resolve()
    jobs = [
        ("projects", _projects_root(), dest_root / "projects"),
        ("file-history", _file_history_root(), dest_root / "file-history"),
    ]
    return [(dest_root, jobs)], None


def _is_list_file(arg: str | None) -> bool:
    return bool(arg) and arg.endswith(".txt") and Path(arg).is_file()


def _build_list_jobs(list_path: Path, payload_cwd: str) -> tuple[list[tuple], str | None]:
    """`--only <file.txt>`: back every listed repo into ONE archive at the CWD
    (`<cwd>/projects/...` + `<cwd>/file-history/...`), like the rsync script."""
    repos = _read_repo_list(list_path)
    if not repos:
        return [], f"--only list {list_path} contained no repo paths"
    dest_root = Path(payload_cwd).resolve()
    jobs: list[tuple] = []
    for repo in repos:
        jobs.extend(_repo_jobs(repo, dest_root))
    if not jobs:
        return [], "no recorded sessions found for the listed repos"
    return [(dest_root, jobs)], None


def _resolve_repos(mode: str, arg: str | None, payload_cwd: str) -> tuple[list[str], str | None]:
    if mode != "only":
        return [payload_cwd], None
    if not arg:
        return [], "--only requires a path or .txt file"
    return [arg], None


def _build_repo_group(repo: str) -> tuple | None:
    dest_root = Path(repo).resolve() / ".claude-data"
    jobs = _repo_jobs(repo, dest_root)
    return (dest_root, jobs) if jobs else None


def _repo_jobs(repo: str, dest_root: Path) -> list[tuple]:
    """Build (label, src, dest) jobs for one repo's sessions + file-history."""
    encoded = _derive_project_dir(str(Path(repo).resolve()))
    src_project = _projects_root() / encoded
    if not src_project.is_dir():
        return []
    jobs = [(f"projects/{encoded}", src_project, dest_root / "projects" / encoded)]
    for uuid in _resolve_session_uuids(src_project):
        _append_history_job(jobs, uuid, dest_root)
    return jobs


def _append_history_job(jobs: list[tuple], uuid: str, dest_root: Path) -> None:
    fh_src = _file_history_root() / uuid
    if fh_src.is_dir():
        jobs.append((f"file-history/{uuid}", fh_src, dest_root / "file-history" / uuid))


def _run_sync(mode: str, arg: str | None, payload_cwd: str, dry_run: bool) -> str:
    groups, error = _build_jobs(mode, arg, payload_cwd)
    if error:
        return f"/sync-jsonl-projects: {error}"

    ts = _timestamp()
    blocks: list[str] = []
    totals = {"new": 0, "mod": 0}
    written_logs: list[str] = []

    for dest_root, jobs in groups:
        blocks.append(_sync_one_dest(dest_root, jobs, ts, mode, dry_run, totals, written_logs))

    if not dry_run and written_logs:
        _write_pointer(written_logs)

    return _assemble_summary(mode, dry_run, blocks, totals["new"], totals["mod"])


def _sync_one_dest(
    dest_root: Path, jobs: list[tuple], ts: str, mode: str, dry_run: bool,
    totals: dict, written_logs: list[str],
) -> str:
    log_dir = dest_root / ".sync-logs"
    backup_root = log_dir / "backups" / f"sync-{ts}"
    log_lines: list[str] = []
    group_summary: list[tuple[str, list[str], list[str]]] = []

    for label, src, dest in jobs:
        new_files, mod_files = _run_one_job(label, src, dest, backup_root, dry_run, log_lines)
        if new_files or mod_files:
            group_summary.append((label, new_files, mod_files))
            totals["new"] += len(new_files)
            totals["mod"] += len(mod_files)

    if not dry_run:
        _finalize_dest(dest_root, log_dir, ts, mode, backup_root, log_lines, written_logs)
    return _format_group(dest_root, group_summary)


def _run_one_job(
    label: str, src: Path, dest: Path, backup_root: Path, dry_run: bool, log_lines: list[str]
) -> tuple[list[str], list[str]]:
    backup_dir = None if dry_run else (backup_root / label)
    itemized = _rsync_job(src, dest, backup_dir, dry_run)
    new_files: list[str] = []
    mod_files: list[str] = []
    for line in itemized:
        _classify_line(line, label, dest, dry_run, log_lines, new_files, mod_files)
    return new_files, mod_files


def _finalize_dest(
    dest_root: Path, log_dir: Path, ts: str, mode: str, backup_root: Path,
    log_lines: list[str], written_logs: list[str],
) -> None:
    _ensure_gitignore(dest_root)
    if log_lines:
        log_path = _write_log(log_dir, ts, mode, dest_root, backup_root, log_lines)
        written_logs.append(str(log_path))
        _prune_old_logs(log_dir, keep=_RETENTION)
    elif backup_root.exists():
        shutil.rmtree(backup_root, ignore_errors=True)


def _run_undo(dry_run: bool) -> str:
    log_paths = _read_pointer()
    if not log_paths:
        return "/sync-jsonl-projects --undo: nothing to undo (no recent sync recorded)."

    blocks: list[str] = []
    totals = {"del": 0, "restore": 0}
    for lp in log_paths:
        blocks.append(_undo_one_log(Path(lp), dry_run, totals))

    if not dry_run:
        _clear_pointer()

    verb = "Would undo" if dry_run else "Undid"
    head = f"{verb} last sync: {totals['del']} file(s) deleted, {totals['restore']} restored."
    return "\n".join([head, ""] + blocks)


def _undo_one_log(log_path: Path, dry_run: bool, totals: dict) -> str:
    if not log_path.is_file():
        return f"  (log missing: {log_path})"
    dest_root, backup_root, entries = _parse_log(log_path)
    deletes: list[str] = []
    restores: list[str] = []
    for code, label, rel in entries:
        _undo_entry(code, label, rel, dest_root, backup_root, dry_run, deletes, restores)
    totals["del"] += len(deletes)
    totals["restore"] += len(restores)
    if not dry_run:
        _remove_log_pair(log_path)
    return _format_undo_group(dest_root, deletes, restores)


def _undo_entry(
    code: str, label: str, rel: str, dest_root: Path, backup_root: Path,
    dry_run: bool, deletes: list[str], restores: list[str],
) -> None:
    dest_abs = dest_root / label / rel
    if _is_new_file(code):
        deletes.append(str(dest_abs))
        if not dry_run:
            _delete_file(dest_abs)
        return
    restores.append(str(dest_abs))
    if not dry_run:
        _restore_file(backup_root / label / rel, dest_abs)

def sync_main() -> int:
    """UserPromptSubmit entry point for `/sync-jsonl-projects`."""
    plugin_root = _util_resolvePluginRoot()
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    raw = sys.stdin.read()
    if '"/sync-jsonl-projects' not in raw:
        return 0

    hookjson_checkRequirements("sync-jsonl-projects", "rsync")

    payload = _load_payload(raw)
    prompt = _match_prompt(payload)
    if prompt is None:
        return 0

    parsed = _parse_args(prompt[len("/sync-jsonl-projects"):].strip())
    if parsed["error"]:
        print(hookjson_emitBlock(f"/sync-jsonl-projects: {parsed['error']}"))
        return 0

    if parsed["mode"] == "undo":
        summary = _run_undo(parsed["dry_run"])
    else:
        cwd_val = payload.get("cwd")
        cwd = cwd_val if isinstance(cwd_val, str) and cwd_val else os.getcwd()
        summary = _run_sync(parsed["mode"], parsed["arg"], cwd, parsed["dry_run"])

    print(hookjson_emitBlock(summary))
    return 0

def _load_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _match_prompt(payload: dict) -> str | None:
    """Return the `/sync-jsonl-projects` prompt, or None if not a match for us."""
    prompt = payload.get("prompt") or ""
    if not isinstance(prompt, str):
        return None
    prompt = prompt.lstrip()
    if prompt != "/sync-jsonl-projects" and not prompt.startswith("/sync-jsonl-projects "):
        return None
    return prompt
