"""Tests for sync_lib: job resolution, prompt matching, and sync/undo integration."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import common.scripts.sync_lib as S
import common.scripts.sync_lib_rsync as R
from common.scripts.sync_lib import (
    _build_jobs,
    _load_payload,
    _match_prompt,
    _run_sync,
    _run_undo,
)
from common.scripts.sync_lib_paths import _derive_project_dir


# ── _match_prompt / _load_payload ─────────────────────────────────────
def test_load_payload_valid():
    assert _load_payload('{"a": 1}') == {"a": 1}


def test_load_payload_malformed():
    assert _load_payload("not json") == {}


def test_match_prompt_exact():
    assert _match_prompt({"prompt": "/sync-jsonl-projects"}) == "/sync-jsonl-projects"


def test_match_prompt_with_args():
    assert _match_prompt({"prompt": "/sync-jsonl-projects --undo"}) == "/sync-jsonl-projects --undo"


def test_match_prompt_non_match():
    assert _match_prompt({"prompt": "/something-else"}) is None


def test_match_prompt_substring_not_command():
    assert _match_prompt({"prompt": "talk about /sync-jsonl-projects"}) is None


# ── _build_jobs ───────────────────────────────────────────────────────
def test_build_jobs_all_requires_dest():
    groups, error = _build_jobs("all", None, "/cwd")
    assert error is not None and groups == []


def test_build_jobs_all_builds_two_jobs(tmp_path: Path):
    groups, error = _build_jobs("all", str(tmp_path / "dest"), "/cwd")
    assert error is None
    (dest_root, jobs) = groups[0]
    labels = [j[0] for j in jobs]
    assert labels == ["projects", "file-history"]


def test_build_jobs_cwd_no_sessions_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(S, "_projects_root", lambda: tmp_path / "projects")
    groups, error = _build_jobs("cwd", None, str(tmp_path / "repo"))
    assert error is not None and groups == []


def test_build_jobs_only_missing_arg_errors():
    groups, error = _build_jobs("only", None, "/cwd")
    assert error is not None


# ── integration: _run_sync + _run_undo ────────────────────────────────
@pytest.fixture
def sync_world(tmp_path: Path, monkeypatch):
    """Build a fake ~/.claude source tree + a repo, with roots/pointer patched."""
    if shutil.which("rsync") is None:
        pytest.skip("rsync not available")

    fake_projects = tmp_path / "claude" / "projects"
    fake_fh = tmp_path / "claude" / "file-history"
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    uuid = "11111111-1111-1111-1111-111111111111"
    encoded = _derive_project_dir(str(repo.resolve()))
    proj_dir = fake_projects / encoded
    proj_dir.mkdir(parents=True)
    (proj_dir / f"{uuid}.jsonl").write_text('{"type":"session"}\n')
    (proj_dir / uuid / "subagents").mkdir(parents=True)
    (proj_dir / uuid / "subagents" / "agent-a.jsonl").write_text("{}\n")
    fh_dir = fake_fh / uuid
    fh_dir.mkdir(parents=True)
    (fh_dir / "abc123@v1").write_text("snapshot\n")

    monkeypatch.setattr(S, "_projects_root", lambda: fake_projects)
    monkeypatch.setattr(S, "_file_history_root", lambda: fake_fh)
    monkeypatch.setattr(R, "_UNDO_POINTER", tmp_path / ".claude-sync-last")
    return {"repo": repo, "uuid": uuid, "encoded": encoded, "tmp": tmp_path}


def test_run_sync_dry_run_no_writes(sync_world):
    repo = sync_world["repo"]
    summary = _run_sync("cwd", None, str(repo), dry_run=True)
    assert "Would sync" in summary
    assert not (repo / ".claude-data").exists()


def test_run_sync_creates_backup_and_gitignore(sync_world):
    repo = sync_world["repo"]
    encoded = sync_world["encoded"]
    uuid = sync_world["uuid"]
    summary = _run_sync("cwd", None, str(repo), dry_run=False)

    assert "Synced (cwd mode)" in summary
    sess = repo / ".claude-data" / "projects" / encoded / f"{uuid}.jsonl"
    snap = repo / ".claude-data" / "file-history" / uuid / "abc123@v1"
    assert sess.is_file() and snap.is_file()
    # gitignore updated
    assert ".claude-data" in (repo / ".gitignore").read_text()
    # log + pointer written
    logs = list((repo / ".claude-data" / ".sync-logs").glob("sync-*.log"))
    assert len(logs) == 1
    assert R._read_pointer() == [str(logs[0])]


def test_run_sync_twice_second_is_noop(sync_world):
    repo = sync_world["repo"]
    _run_sync("cwd", None, str(repo), dry_run=False)
    summary2 = _run_sync("cwd", None, str(repo), dry_run=False)
    assert summary2 == "Everything already in sync — nothing to transfer."


def test_run_undo_deletes_new_files(sync_world):
    repo = sync_world["repo"]
    encoded = sync_world["encoded"]
    uuid = sync_world["uuid"]
    _run_sync("cwd", None, str(repo), dry_run=False)
    sess = repo / ".claude-data" / "projects" / encoded / f"{uuid}.jsonl"
    assert sess.is_file()

    undo_summary = _run_undo(dry_run=False)
    assert "Undid last sync" in undo_summary
    assert not sess.is_file()
    assert R._read_pointer() == []


def test_run_undo_dry_run_keeps_files(sync_world):
    repo = sync_world["repo"]
    encoded = sync_world["encoded"]
    uuid = sync_world["uuid"]
    _run_sync("cwd", None, str(repo), dry_run=False)
    sess = repo / ".claude-data" / "projects" / encoded / f"{uuid}.jsonl"

    undo_summary = _run_undo(dry_run=True)
    assert "Would undo" in undo_summary
    assert sess.is_file()  # untouched
    assert R._read_pointer() != []  # pointer preserved


def test_run_undo_nothing_recorded(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "_UNDO_POINTER", tmp_path / "nope")
    assert "nothing to undo" in _run_undo(dry_run=False)


def test_only_list_archives_into_cwd(sync_world):
    """--only <list.txt> backs listed repos into ONE archive at the CWD, like the
    rsync script: <cwd>/projects/<encoded>/ and <cwd>/file-history/<uuid>/."""
    repo = sync_world["repo"]
    encoded = sync_world["encoded"]
    uuid = sync_world["uuid"]
    archive = sync_world["tmp"] / "archive"
    archive.mkdir()
    list_file = archive / "tracked.txt"
    list_file.write_text(f"# repos\n{repo}\n")

    summary = _run_sync("only", str(list_file), str(archive), dry_run=False)
    assert "Synced (only mode)" in summary
    # Central layout rooted at the CWD (archive), NOT repo/.claude-data.
    assert (archive / "projects" / encoded / f"{uuid}.jsonl").is_file()
    assert (archive / "file-history" / uuid / "abc123@v1").is_file()
    assert not (repo / ".claude-data").exists()
    # One log + pointer at the archive root.
    assert len(list((archive / ".sync-logs").glob("sync-*.log"))) == 1


def test_undo_restores_modified_file_from_backup(sync_world):
    """Sync v1, modify source to v2, re-sync (backs up v1), undo -> v1 restored."""
    repo = sync_world["repo"]
    encoded = sync_world["encoded"]
    uuid = sync_world["uuid"]
    src_sess = sync_world["tmp"] / "claude" / "projects" / encoded / f"{uuid}.jsonl"
    dest_sess = repo / ".claude-data" / "projects" / encoded / f"{uuid}.jsonl"

    _run_sync("cwd", None, str(repo), dry_run=False)
    v1 = dest_sess.read_text()

    # Modify the source and re-sync; the changed dest file should be backed up.
    src_sess.write_text('{"type":"session","v":2,"more":"data"}\n')
    summary2 = _run_sync("cwd", None, str(repo), dry_run=False)
    assert "modified" in summary2
    assert dest_sess.read_text() != v1

    # Undo the second sync -> the modified file is restored to v1.
    _run_undo(dry_run=False)
    assert dest_sess.read_text() == v1
