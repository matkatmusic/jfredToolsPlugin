"""rsync execution, itemize parsing, and log/backup/pointer management for the
sync-jsonl-projects skill."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Global pointer to the most recent invocation's log file(s), one path per line.
# Bare `--undo` reads this to know what to reverse, regardless of CWD.
_UNDO_POINTER = Path.home() / ".claude-sync-last"

# How many log+backup pairs to retain per destination .sync-logs/ directory.
_RETENTION = 5


# ── itemize-changes code classification ───────────────────────────────
def _is_new_file(code: str) -> bool:
    """True if an itemize code marks a newly created regular file (`>f+++++++++`)."""
    return code.startswith(">f") and set(code[2:]) == {"+"}


def _is_changed_file(code: str) -> bool:
    """True if an itemize code marks a transferred regular file (new or modified)."""
    return code.startswith(">f")


def _parse_itemize(line: str) -> tuple[str, str]:
    """Split an itemize line into (code, relpath). Code is the leading token."""
    parts = line.split(" ", 1)
    code = parts[0]
    rel = parts[1] if len(parts) > 1 else ""
    return code, rel


def _file_is_new(code: str, dest: Path, rel: str, dry_run: bool) -> bool:
    """Decide whether a transferred file is new vs modified.

    openrsync's dry-run reports new files with dots (`>f.......`), so the code
    alone can't distinguish new from modified during a preview. In dry-run no
    writes happen, so destination absence is an accurate signal. For real
    transfers the file already exists by the time we parse, so we rely on the
    itemize code (`>f+++...` marks a new file across rsync flavors).
    """
    if dry_run:
        return not (dest / rel).exists()
    return _is_new_file(code)


def _classify_line(
    line: str, label: str, dest: Path, dry_run: bool,
    log_lines: list[str], new_files: list[str], mod_files: list[str],
) -> None:
    """Record one itemize line into the log and the new/modified buckets."""
    code, rel = _parse_itemize(line)
    if not _is_changed_file(code):
        return
    log_lines.append(f"{code}\t{label}\t{rel}")
    if _file_is_new(code, dest, rel, dry_run):
        new_files.append(rel)
    else:
        mod_files.append(rel)


# ── rsync invocation ──────────────────────────────────────────────────
def _rsync_job(src: Path, dest: Path, backup_dir: Path | None, dry_run: bool) -> list[str]:
    """Run one rsync src/ -> dest/ and return its raw `--itemize-changes` lines.

    When `backup_dir` is provided (non-dry-run), overwritten files are preserved
    there via `--backup --backup-dir`, enabling undo of modifications.
    """
    cmd = ["rsync", "-a", "--itemize-changes"]
    if dry_run:
        cmd.append("-n")
    elif backup_dir is not None:
        cmd += ["--backup", "--backup-dir", str(backup_dir)]
    cmd += [f"{str(src).rstrip('/')}/", f"{str(dest).rstrip('/')}/"]

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


# ── log writing / pointer / pruning ───────────────────────────────────
def _write_log(
    log_dir: Path, ts: str, mode: str, dest_root: Path, backup_root: Path, body: list[str]
) -> Path:
    """Write a self-describing sync log and return its path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"sync-{ts}.log"
    header = [
        "# sync-jsonl-projects",
        f"# timestamp: {ts}",
        f"# mode: {mode}",
        f"# dest-root: {dest_root}",
        f"# backup-root: {backup_root}",
        "---",
    ]
    log_path.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    return log_path


def _write_pointer(log_paths: list[str]) -> None:
    """Record the invocation's log paths in the global undo pointer."""
    try:
        _UNDO_POINTER.write_text("\n".join(log_paths) + "\n", encoding="utf-8")
    except OSError:
        pass


def _read_pointer() -> list[str]:
    """Return the log paths recorded in the global undo pointer (newest sync)."""
    if not _UNDO_POINTER.is_file():
        return []
    try:
        text = _UNDO_POINTER.read_text(encoding="utf-8")
    except OSError:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _clear_pointer() -> None:
    _UNDO_POINTER.unlink(missing_ok=True)


def _prune_old_logs(log_dir: Path, keep: int) -> None:
    """Keep only the newest `keep` log+backup pairs in `log_dir`."""
    logs = sorted(log_dir.glob("sync-*.log"))
    excess = logs[:-keep] if len(logs) > keep else []
    for old in excess:
        _remove_log_pair(old)


def _remove_log_pair(log_path: Path) -> None:
    """Delete a log file and its sibling backup directory."""
    ts = log_path.stem[len("sync-"):]
    log_path.unlink(missing_ok=True)
    backup = log_path.parent / "backups" / f"sync-{ts}"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


# ── log parsing / restore (undo) ──────────────────────────────────────
def _parse_log(log_path: Path) -> tuple[Path, Path, list[tuple[str, str, str]]]:
    """Parse a sync log into (dest_root, backup_root, [(code, label, rel), ...])."""
    dest_root = Path("/")
    backup_root = Path("/")
    entries: list[tuple[str, str, str]] = []
    in_body = False
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line == "---":
            in_body = True
        elif in_body:
            _append_entry(entries, line)
        else:
            dest_root, backup_root = _read_header_line(line, dest_root, backup_root)
    return dest_root, backup_root, entries


def _read_header_line(line: str, dest_root: Path, backup_root: Path) -> tuple[Path, Path]:
    if line.startswith("# dest-root:"):
        return Path(line.split(":", 1)[1].strip()), backup_root
    if line.startswith("# backup-root:"):
        return dest_root, Path(line.split(":", 1)[1].strip())
    return dest_root, backup_root


def _append_entry(entries: list[tuple[str, str, str]], line: str) -> None:
    parts = line.split("\t")
    if len(parts) == 3:
        entries.append((parts[0], parts[1], parts[2]))


def _delete_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _restore_file(backup_abs: Path, dest_abs: Path) -> None:
    """Copy a backed-up file back over the destination (best-effort)."""
    if not backup_abs.is_file():
        return
    try:
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_abs, dest_abs)
    except OSError:
        pass
