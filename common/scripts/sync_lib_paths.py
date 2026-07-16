"""Path, argument, and gitignore helpers for the sync-jsonl-projects skill."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Claude Code encodes a project dir name by replacing every character that is
# not ASCII-alphanumeric with `-` (so `/`, `.`, and spaces all become `-`),
# without collapsing runs. e.g. `/Users/me/.claude/x y` -> `-Users-me--claude-x-y`.
_PROJECT_DIR_NONALNUM = re.compile(r"[^a-zA-Z0-9]")


# ── Source roots ──────────────────────────────────────────────────────
def _projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def _file_history_root() -> Path:
    return Path.home() / ".claude" / "file-history"


# ── Path / arg helpers ────────────────────────────────────────────────
def _derive_project_dir(repo_path: str) -> str:
    """Convert an absolute repo path to its Claude project dir name.

    Claude Code replaces every non-alphanumeric character with `-` (so `/`,
    `.`, and spaces all become `-`), without collapsing runs. For example
    `/Users/me/Desktop/claude code src` -> `-Users-me-Desktop-claude-code-src`
    and `/Users/me/.claude/x` -> `-Users-me--claude-x`. Trailing slashes are
    ignored.
    """
    norm = str(Path(repo_path)).rstrip("/")
    return _PROJECT_DIR_NONALNUM.sub("-", norm)


def _resolve_session_uuids(project_dir: Path) -> list[str]:
    """Return the session UUID stems (`*.jsonl` filenames) under a project dir."""
    if not project_dir.is_dir():
        return []
    return sorted(p.stem for p in project_dir.glob("*.jsonl"))


# Flags that consume the following token as a path argument.
_VALUE_FLAGS = {
    "--only": "--only requires a path or .txt file argument",
    "--all": "--all requires a destination path argument",
}


def _parse_args(remainder: str) -> dict:
    """Parse the text after `/sync-jsonl-projects` into a mode descriptor.

    Returns {mode: 'cwd'|'only'|'all'|'undo', arg: str|None, dry_run: bool,
    error: str|None}. Path args have `~` expanded.

    Note: tokens are split on whitespace, so paths containing spaces are not
    supported (acceptable for slash-command usage).
    """
    tokens = remainder.split()
    state = {"mode": "cwd", "arg": None, "dry_run": False, "error": None}

    i = 0
    while i < len(tokens):
        i = _consume_token(tokens, i, state)
    return state


def _consume_token(tokens: list[str], i: int, state: dict) -> int:
    """Apply tokens[i] to `state`; return the next index to read."""
    tok = tokens[i]
    if tok == "--dry-run":
        state["dry_run"] = True
    elif tok == "--undo":
        state["mode"] = "undo"
    elif tok in _VALUE_FLAGS:
        state["mode"] = "only" if tok == "--only" else "all"
        if i + 1 >= len(tokens):
            state["error"] = _VALUE_FLAGS[tok]
            return i + 1
        state["arg"] = os.path.expanduser(tokens[i + 1])
        return i + 2
    else:
        state["error"] = f"unrecognized argument: {tok}"
    return i + 1


def _is_repo_list_entry(line: str) -> bool:
    """True for a non-blank, non-comment repo-list line."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _read_repo_list(list_file: Path) -> list[str]:
    """Read a repo-list .txt: one path per line, `#` comments and blanks ignored."""
    try:
        raw_lines = list_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [os.path.expanduser(ln.strip()) for ln in raw_lines if _is_repo_list_entry(ln)]


def _timestamp() -> str:
    """Filesystem-safe UTC timestamp, e.g. 20260613T142500Z."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ── git / gitignore ───────────────────────────────────────────────────
def _git_repo_root(path: Path) -> str:
    """Return the git toplevel for `path`, or '' if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, FileNotFoundError):
        return ""


def _ensure_gitignore(dest_root: Path) -> None:
    """If `dest_root` is a `.claude-data` dir inside a git repo, ensure the repo's
    .gitignore lists `.claude-data`."""
    if dest_root.name != ".claude-data":
        return
    repo = dest_root.parent
    if not (repo / ".git").exists():
        return
    gitignore = repo / ".gitignore"
    entry = ".claude-data"
    existing = ""
    if gitignore.exists():
        try:
            existing = gitignore.read_text(encoding="utf-8")
        except OSError:
            return
    lines = [ln.strip() for ln in existing.splitlines()]
    if entry in lines or entry + "/" in lines:
        return
    try:
        prefix = "" if existing == "" or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}{entry}\n")
    except OSError:
        return
