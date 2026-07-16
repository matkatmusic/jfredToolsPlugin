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

## Tests

```sh
pytest
```
