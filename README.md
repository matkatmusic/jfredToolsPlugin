# jfredToolsPlugin

A Claude Code plugin carrying two commands, usable from any directory:

- `/run-scenario <scenario.txt>` — spawn a Claude agent in a named tmux session and
  drive it through a scenario file line-by-line (prompts, file edits, rewinds,
  completion signaling).
- `/sync-jsonl-projects [--only <path|list.txt> | --all <dest> | --undo] [--dry-run]` —
  sync Claude Code session JSONL files and file-history to a local backup.

## Setup

```sh
git submodule update --init --recursive
```

The python imports `tmux_lib` and `claude_plugin_lib` from the `external/` git
submodules — nothing is pip-installed.

## Enabling the plugin

Launch Claude Code with the plugin directory (the flag is `--plugin-dir`, which loads a
plugin — NOT `--add-dir`, which only grants file access):

```sh
claude --plugin-dir /path/to/jfred-clone/jfredToolsPlugin
```

This repo ships as a submodule of [JFRED](https://github.com/matkatmusic/JFRED);
JFRED's `install.sh` can add a `claude()` wrapper to your `~/.zshrc` that passes the
flag automatically (it asks before touching `~/.zshrc`). The wrapper bakes in the
absolute path of the clone it was installed from, so re-run it if the clone moves.

## Scenario prerequisite: the context-mode plugin

Many scenario files instruct the driven agent to run scripts through the
context-mode MCP sandbox (`ctx_execute` / `ctx_batch_execute`). If the
context-mode plugin is not installed in the capture environment, the agent
cannot follow those steps and the captured run diverges from the scenario.

Scenarios that require it (any scenario whose steps invoke `ctx_execute` or
`ctx_batch_execute` — verify with
`grep -l 'ctx_execute\|ctx_batch_execute' scenarios/*.txt`):

s32, s36, s37, s38, s42, s43, s44, s74, s75, s80, s83, s84, s85,
s87-demo-composite.

This applies to clean-environment captures too: a capture run under a fresh
`CLAUDE_CONFIG_DIR` must still install the context-mode plugin before
`/run-scenario` is invoked, or the MCP steps above will not be executable.

## Tests

```sh
pytest
```
