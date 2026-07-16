"""Summary formatting for the sync-jsonl-projects skill."""
from __future__ import annotations

from pathlib import Path

# Max files listed per group in the surfaced summary before eliding.
_SUMMARY_LIST_CAP = 50


def _format_group(
    dest_root: Path, group_summary: list[tuple[str, list[str], list[str]]]
) -> str:
    """Render one destination's per-label new/modified file groups."""
    if not group_summary:
        return f"{dest_root}: nothing new."
    out = [f"{dest_root}:"]
    for label, new_files, mod_files in group_summary:
        out.append(
            f"  === {label} ({len(new_files)} new, {len(mod_files)} modified) ==="
        )
        out.extend(_render_file_lines(new_files + mod_files))
    return "\n".join(out)


def _render_file_lines(files: list[str]) -> list[str]:
    shown = files[:_SUMMARY_LIST_CAP]
    lines = [f"    {rel}" for rel in shown]
    remaining = len(files) - len(shown)
    if remaining > 0:
        lines.append(f"    ... and {remaining} more")
    return lines


def _format_undo_group(dest_root: Path, deletes: list[str], restores: list[str]) -> str:
    """Render one destination's undo result."""
    out = [f"{dest_root}: {len(deletes)} deleted, {len(restores)} restored"]
    out.extend(f"    - {d}" for d in deletes[:_SUMMARY_LIST_CAP])
    return "\n".join(out)


def _assemble_summary(
    mode: str, dry_run: bool, blocks: list[str], total_new: int, total_mod: int
) -> str:
    """Combine per-destination blocks into the final surfaced summary."""
    if total_new == 0 and total_mod == 0:
        return "Everything already in sync — nothing to transfer."
    verb = "Would sync" if dry_run else "Synced"
    head = f"{verb} ({mode} mode): {total_new} new, {total_mod} modified."
    return "\n".join([head, ""] + blocks)
