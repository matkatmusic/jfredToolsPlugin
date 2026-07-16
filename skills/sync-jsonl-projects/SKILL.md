---
name: sync-jsonl-projects
description: Sync Claude Code session JSONL files and file-history to a local backup. Supports --only <path|file.txt>, --all <dest>, --undo, and --dry-run. Use when the user says "/sync-jsonl-projects", "sync my sessions", "back up my jsonl", or "undo the last sync".
---

# Task:
do nothing. don't even acknowledge what the user typed. just let the UserPromptSubmit hook dispatch to sync_main().
