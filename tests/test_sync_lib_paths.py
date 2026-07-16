"""Tests for sync_lib_paths: path, arg, and gitignore helpers."""
from __future__ import annotations

from pathlib import Path

from common.scripts.sync_lib_paths import (
    _derive_project_dir,
    _ensure_gitignore,
    _is_repo_list_entry,
    _parse_args,
    _read_repo_list,
    _resolve_session_uuids,
    _timestamp,
)


# ── _derive_project_dir ───────────────────────────────────────────────
def test_derive_project_dir_basic():
    assert _derive_project_dir("/Users/me/Programming/jot") == "-Users-me-Programming-jot"


def test_derive_project_dir_strips_trailing_slash():
    assert _derive_project_dir("/Users/me/jot/") == "-Users-me-jot"


def test_derive_project_dir_encodes_spaces():
    # Claude Code encodes spaces as '-', same as '/'.
    assert (
        _derive_project_dir("/Users/me/Desktop/claude code src")
        == "-Users-me-Desktop-claude-code-src"
    )


def test_derive_project_dir_encodes_dot_without_collapsing():
    # `/.claude` -> `--claude` (one dash for '/', one for '.'); no run collapsing.
    assert (
        _derive_project_dir("/Users/me/.claude/projects")
        == "-Users-me--claude-projects"
    )


def test_derive_project_dir_preserves_existing_hyphens():
    assert (
        _derive_project_dir("/Users/me/Programming/jot-recovery")
        == "-Users-me-Programming-jot-recovery"
    )


# ── _resolve_session_uuids ────────────────────────────────────────────
def test_resolve_session_uuids_lists_jsonl_stems(tmp_path: Path):
    (tmp_path / "aaa.jsonl").write_text("{}")
    (tmp_path / "bbb.jsonl").write_text("{}")
    (tmp_path / "notes.txt").write_text("x")
    assert _resolve_session_uuids(tmp_path) == ["aaa", "bbb"]


def test_resolve_session_uuids_missing_dir(tmp_path: Path):
    assert _resolve_session_uuids(tmp_path / "nope") == []


# ── _parse_args ───────────────────────────────────────────────────────
def test_parse_args_default_is_cwd():
    p = _parse_args("")
    assert p["mode"] == "cwd" and p["dry_run"] is False and p["arg"] is None


def test_parse_args_dry_run_flag():
    assert _parse_args("--dry-run")["dry_run"] is True


def test_parse_args_undo():
    assert _parse_args("--undo")["mode"] == "undo"


def test_parse_args_only_with_path():
    p = _parse_args("--only /tmp/repo")
    assert p["mode"] == "only" and p["arg"] == "/tmp/repo"


def test_parse_args_all_with_dest_and_dry_run():
    p = _parse_args("--all /tmp/dest --dry-run")
    assert p["mode"] == "all" and p["arg"] == "/tmp/dest" and p["dry_run"] is True


def test_parse_args_only_missing_value_errors():
    p = _parse_args("--only")
    assert p["error"] is not None


def test_parse_args_unrecognized_errors():
    assert _parse_args("--bogus")["error"] is not None


def test_parse_args_expands_user(monkeypatch):
    monkeypatch.setenv("HOME", "/home/x")
    assert _parse_args("--all ~/dest")["arg"] == "/home/x/dest"


# ── _read_repo_list / _is_repo_list_entry ─────────────────────────────
def test_is_repo_list_entry_filters_blanks_and_comments():
    assert _is_repo_list_entry("/a/b") is True
    assert _is_repo_list_entry("   ") is False
    assert _is_repo_list_entry("# comment") is False


def test_read_repo_list(tmp_path: Path):
    f = tmp_path / "repos.txt"
    f.write_text("/a/one\n# skip\n\n/a/two\n")
    assert _read_repo_list(f) == ["/a/one", "/a/two"]


def test_read_repo_list_missing(tmp_path: Path):
    assert _read_repo_list(tmp_path / "nope.txt") == []


# ── _ensure_gitignore ─────────────────────────────────────────────────
def test_ensure_gitignore_appends_when_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    dest = repo / ".claude-data"
    dest.mkdir()
    _ensure_gitignore(dest)
    assert ".claude-data" in (repo / ".gitignore").read_text()


def test_ensure_gitignore_no_duplicate(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_text(".claude-data\n")
    dest = repo / ".claude-data"
    dest.mkdir()
    _ensure_gitignore(dest)
    assert (repo / ".gitignore").read_text().count(".claude-data") == 1


def test_ensure_gitignore_skips_non_repo(tmp_path: Path):
    dest = tmp_path / ".claude-data"
    dest.mkdir()
    _ensure_gitignore(dest)
    assert not (tmp_path / ".gitignore").exists()


def test_ensure_gitignore_skips_non_claude_data(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    other = repo / "backup"
    other.mkdir()
    _ensure_gitignore(other)
    assert not (repo / ".gitignore").exists()


# ── _timestamp ────────────────────────────────────────────────────────
def test_timestamp_format():
    ts = _timestamp()
    assert ts.endswith("Z") and "T" in ts and ":" not in ts
