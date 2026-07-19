Create a task list for everything you end up doing in this session so the user can keep up with what you're doing.  The more granular the task list is, the better.

use the '/ponytail' skill to reduce how much code and context you generate.

## Monitoring for when to start planning

Wait for the handoff document for 'Scenario X-1' to be created, which documents the *implementation* of 'Scenario X-1'. Use the repo-root monitoring script for this — do not hand-roll a loop:

```
./monitor-handoff.sh <X-1> impl
```

Substitute `<X-1>` with the previous scenario's token (e.g. if your X is `s27`, run `./monitor-handoff.sh s26 impl`). The script blocks and exits 0 only when the Implementing agent's completion handoff for 'Scenario X-1' has landed, printing its path. Run it as a Monitor task with a timeout (e.g. 1h).

The agent creating the handoff document for you hasn't finished/launched yet, so wait for the monitor to notify you that your specific 'Scenario X-1' handoff document is ready.

## When the handoff doc lands:

Check if the doc is the scenario you're being tasked with.  
Your specific scenario is 'Scenario X'.  
If the handoff doc is not meant for you, continue monitoring.
If the monitor shuts off or exits due to timing out and you haven't received the 'Scenario X-1' handoff document, respawn the monitor.

## Then: does the engine already handle Scenario X?

Once the handoff for 'Scenario X-1' has landed, run the JSONL for 'Scenario X' through the `reconstruction_cli` tool and compare its output against the on-disk reconstruction for the scenario. The point of this check is to eliminate unnecessary work when the engine already handles the scenario correctly.

- Scenario input data: `/Users/matkatmusicllc/Programming/RevEng-worktrees/api-from-scenarios/scenarios/sX-*.txt`
- Executed output (the JSONL + rendered on-disk files): `/Users/matkatmusicllc/Programming/RevEng-worktrees/api-from-scenarios/scenarios/executed/sX-*/`

Run the CLI from the repo root, passing the scenario's JSONL as the only positional argument:

```
node --import tsx src/reconstruction_cli.ts scenarios/executed/sX-*/*.jsonl
```

Useful flags for inspecting the reconstruction so you can diff it against the on-disk files:
- `--target <path>` — restrict output to a single reconstructed file
- `--verbose` — print each file's full reconstructed content (this is what you compare byte-for-byte against the on-disk file in `scenarios/executed/sX-*/`)
- `--diff` — show the reconstruction as diffs instead of full content
- view flags: `--graphConvo` / `--graphFile` / `--surviving` / `--list-branches` / `--branch <id>` (both graphs print by default)

Compare the CLI's reconstructed history/content for every file the JSONL touches against the rendered on-disk files in `scenarios/executed/sX-*/`.

**If `reconstruction_cli` produces the correct reconstruction history for every file touched in the JSONL**, the engine already handles Scenario X. Skip the handoff read and the gap analysis entirely — jump straight to writing a short plan with exactly these details:
```
reconstruction_cli processed Scenario X without needing any engine modifications.  Create a single test that captures the output when the JSONL for Scenario X is used as the input, that can be verified as the expected output every time the test for that scenario is run.
```
Keep the plan short — no need to blast the context window with unnecessary info. Then write the handoff (see ## Handoff Specs) and stop.

**If the output is NOT correct**, the engine has a gap. Continue with ## Planning below: read the handoff and its linked files, find the gap with subagents, write the plan, then the handoff.

## Planning:

Read the handoff doc to prepare for writing the plan for implementing handling 'Scenario X', found in `scenarios/executed/`.  
Be sure to read the `MUST READ` file linked at the top of the handoff. 
Then read `~/.claude/guides/planning.md`.

Using the `reconstruction_cli` output you already captured above, inspect the codebase with subagents to identify where the gaps are when the Scenario X JSONL is run through the engine.
Use subagents where possible to keep your context window clear.

Then create the plan for 'Scenario X' so that the `reconstruction_cli` engine correctly handles the file change events in the JSONL.  The plan will be implemented in another session.

## Handoff Specs:

When the plan is finished, write a handoff doc using the '/jot:handoff-prompt' skill.

Include 'create handoff' in your task list for the next agent, who will implement the plan you create. 

When you write the handoff, put 'MUST READ: plans/script-handling.txt' near the top, after the header of the handoff tmeplate.

## After the handoff:

Don't write a summary to me after you create the handoff, just provide the path to the handoff, as the skill specifies. 

Do not verify if the monitoring script parses the handoff correctly to trigger the next agent's session, it has already been confirmed that the monitoring script does.