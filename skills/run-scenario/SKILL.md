---
name: run-scenario
description: Spawn a Claude agent in a named tmux session and drive it through a scenario file line-by-line. Sends prompts, performs file edits, sends rewinds, waits for agent completion via hook signaling, and tracks progress. Use when user types "/run-scenario <scenario.txt>".
argument-hint: <scenario-file-path>
---

# Task:
do nothing. don't even acknowledge what the user typed. just let the UserPromptSubmit hook do its thing.
