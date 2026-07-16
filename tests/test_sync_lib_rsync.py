"""Tests for sync_lib_rsync: itemize parsing, logs, pointer, pruning, restore."""
from __future__ import annotations

from pathlib import Path

import common.scripts.sync_lib_rsync as R
from common.scripts.sync_lib_rsync import (
    _classify_line,
    _clear_pointer,
    _delete_file,
    _file_is_new,
    _is_changed_file,
    _is_new_file,
    _parse_itemize,
    _parse_log,
    _prune_old_logs,
    _read_pointer,
    _remove_log_pair,
    _restore_file,
    _write_log,
    _write_pointer,
)


# ── itemize classification ────────────────────────────────────────────
def test_is_new_file_true_for_all_plus():
    assert _is_new_file(">f+++++++++") is True


def test_is_new_file_false_for_modified():
    assert _is_new_file(">f.st......") is False


def test_is_changed_file_matches_any_transfer():
    assert _is_changed_file(">f.st......") is True
    assert _is_changed_file("cd+++++++++") is False


def test_parse_itemize_splits_code_and_path():
    assert _parse_itemize(">f+++++++++ a/b.jsonl") == (">f+++++++++", "a/b.jsonl")


def test_parse_itemize_no_path():
    assert _parse_itemize(">f+++++++++") == (">f+++++++++", "")


# ── _file_is_new (rsync-flavor-robust new detection) ──────────────────
def test_file_is_new_dry_run_uses_dest_absence(tmp_path: Path):
    # openrsync dry-run codes new files with dots; absence is the real signal.
    assert _file_is_new(">f.......", tmp_path, "missing.txt", dry_run=True) is True


def test_file_is_new_dry_run_existing_is_modified(tmp_path: Path):
    (tmp_path / "there.txt").write_text("x")
    assert _file_is_new(">f.s.....", tmp_path, "there.txt", dry_run=True) is False


def test_file_is_new_real_uses_code(tmp_path: Path):
    assert _file_is_new(">f+++++++", tmp_path, "any.txt", dry_run=False) is True
    assert _file_is_new(">f.s.....", tmp_path, "any.txt", dry_run=False) is False


# ── _classify_line ────────────────────────────────────────────────────
def test_classify_line_new_real(tmp_path: Path):
    log, new, mod = [], [], []
    _classify_line(">f+++++++ a.jsonl", "projects/p", tmp_path, False, log, new, mod)
    assert new == ["a.jsonl"] and mod == []
    assert log == [">f+++++++\tprojects/p\ta.jsonl"]


def test_classify_line_skips_non_file(tmp_path: Path):
    log, new, mod = [], [], []
    _classify_line("cd+++++++ ./", "projects/p", tmp_path, False, log, new, mod)
    assert new == [] and mod == [] and log == []


# ── log write / parse roundtrip ───────────────────────────────────────
def test_write_and_parse_log_roundtrip(tmp_path: Path):
    log_dir = tmp_path / ".sync-logs"
    dest_root = tmp_path / ".claude-data"
    backup_root = log_dir / "backups" / "sync-20260613T000000Z"
    body = [
        ">f+++++++++\tprojects/enc\tsess.jsonl",
        ">f.st......\tfile-history/uuid\tx@v1",
    ]
    log_path = _write_log(log_dir, "20260613T000000Z", "cwd", dest_root, backup_root, body)
    assert log_path.is_file()
    parsed_dest, parsed_backup, entries = _parse_log(log_path)
    assert parsed_dest == dest_root
    assert parsed_backup == backup_root
    assert entries == [
        (">f+++++++++", "projects/enc", "sess.jsonl"),
        (">f.st......", "file-history/uuid", "x@v1"),
    ]


# ── pointer ───────────────────────────────────────────────────────────
def test_pointer_write_read_clear(tmp_path: Path, monkeypatch):
    ptr = tmp_path / ".claude-sync-last"
    monkeypatch.setattr(R, "_UNDO_POINTER", ptr)
    _write_pointer(["/a/log1.log", "/b/log2.log"])
    assert _read_pointer() == ["/a/log1.log", "/b/log2.log"]
    _clear_pointer()
    assert _read_pointer() == []


def test_read_pointer_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "_UNDO_POINTER", tmp_path / "nope")
    assert _read_pointer() == []


# ── pruning ───────────────────────────────────────────────────────────
def test_prune_old_logs_keeps_newest(tmp_path: Path):
    log_dir = tmp_path
    backups = log_dir / "backups"
    stamps = [f"sync-2026010{i}T000000Z" for i in range(1, 8)]
    for s in stamps:
        (log_dir / f"{s}.log").write_text("x")
        (backups / s).mkdir(parents=True)
    _prune_old_logs(log_dir, keep=5)
    remaining = sorted(p.stem for p in log_dir.glob("sync-*.log"))
    assert len(remaining) == 5
    # Oldest two removed, along with their backup dirs.
    assert not (backups / stamps[0]).exists()
    assert (backups / stamps[-1]).exists()


def test_remove_log_pair(tmp_path: Path):
    log = tmp_path / "sync-20260101T000000Z.log"
    log.write_text("x")
    backup = tmp_path / "backups" / "sync-20260101T000000Z"
    backup.mkdir(parents=True)
    _remove_log_pair(log)
    assert not log.exists() and not backup.exists()


# ── delete / restore ──────────────────────────────────────────────────
def test_delete_file(tmp_path: Path):
    f = tmp_path / "x"
    f.write_text("y")
    _delete_file(f)
    assert not f.exists()


def test_restore_file_copies_back(tmp_path: Path):
    backup = tmp_path / "bk" / "x"
    backup.parent.mkdir()
    backup.write_text("old")
    dest = tmp_path / "dest" / "x"
    _restore_file(backup, dest)
    assert dest.read_text() == "old"


def test_restore_file_missing_backup_noop(tmp_path: Path):
    dest = tmp_path / "dest" / "x"
    _restore_file(tmp_path / "nope", dest)
    assert not dest.exists()
