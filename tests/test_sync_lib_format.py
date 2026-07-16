"""Tests for sync_lib_format: summary rendering."""
from __future__ import annotations

from pathlib import Path

from common.scripts.sync_lib_format import (
    _assemble_summary,
    _format_group,
    _format_undo_group,
)


def test_format_group_nothing_new(tmp_path: Path):
    assert _format_group(tmp_path, []) == f"{tmp_path}: nothing new."


def test_format_group_lists_files(tmp_path: Path):
    out = _format_group(tmp_path, [("projects/enc", ["a.jsonl"], ["b.jsonl"])])
    assert "=== projects/enc (1 new, 1 modified) ===" in out
    assert "a.jsonl" in out and "b.jsonl" in out


def test_format_group_caps_long_lists(tmp_path: Path):
    files = [f"f{i}.jsonl" for i in range(60)]
    out = _format_group(tmp_path, [("projects/enc", files, [])])
    assert "... and 10 more" in out


def test_format_undo_group(tmp_path: Path):
    out = _format_undo_group(tmp_path, ["/a/x", "/a/y"], ["/a/z"])
    assert "2 deleted, 1 restored" in out
    assert "- /a/x" in out


def test_assemble_summary_empty():
    out = _assemble_summary("cwd", False, [], 0, 0)
    assert out == "Everything already in sync — nothing to transfer."


def test_assemble_summary_dry_run_verb():
    out = _assemble_summary("all", True, ["block"], 3, 1)
    assert out.startswith("Would sync (all mode): 3 new, 1 modified.")


def test_assemble_summary_real_verb():
    out = _assemble_summary("cwd", False, ["block"], 2, 0)
    assert out.startswith("Synced (cwd mode): 2 new, 0 modified.")
