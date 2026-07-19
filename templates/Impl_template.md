Create a task list for everything you end up doing in this session so the user can keep up with what you're doing.  The more granular the task list is, the better.

use the '/ponytail' skill to reduce how much code and context you generate.

Read everything in `~/.claude/guides/`

## Monitor for the handoff:
Then wait for the Handoff document for 'Scenario X' to be created. Use the repo-root monitoring script for this — do not hand-roll a loop:

```
./monitor-handoff.sh <X> plan
```

Substitute `<X>` with your scenario's token (e.g. if your X is `s27`, run `./monitor-handoff.sh s27 plan`). The script blocks and exits 0 only when the Planning agent's handoff for 'Scenario X' (the one that tells you to IMPLEMENT it) has landed, printing its path. Run it as a Monitor task with a timeout (e.g. 1h).
If the monitor shuts off or exits due to timing out and you haven't received the 'Scenario X' handoff document, respawn the monitor.

**Do not begin implementing** the plan file for 'Scenario X' when the plan lands.  Wait for the handoff document, which the script detects.  The plan file always lands before the handoff.

The agent creating the 'Scenario X' plan for you hasn't finished/launched yet, so wait for the monitor to notify you that your specific Handoff document is ready. 

## Before implementing:

When the handoff document lands, check if the doc is the scenario you're being tasked with.  
Your specific scenario is 'Scenario X'.  
If the handoff doc is not meant for you, continue monitoring.

When the handoff document lands, read the 'MUST READ' file at the top, then read the handoff itself, then the plan, and any other relevant files linked in the plan. 

## Implementing:
Then begin implementing the plan mentioned within for handling 'Scenario X' using the '/jot:implement' skill. 
Use subagents where possible to keep your context window clear.

The scenario you're implementing engine handling for is here: `/Users/matkatmusicllc/Programming/RevEng-worktrees/api-from-scenarios/scenarios/X-*.txt`.  the `scenarios/executed/X-*/` folder contains the output from the run of that scenario, including the JSONL file and any rendered files. 

Include 'create handoff' in your task list, once you start implementing the plan for 'Scenario X'.

Make your task list detailed, so progress is easily tracked while implementing.  Don't use a singular task item to represent the entire "implement engine handling for Scenario X" task.   The more granular the task list, the better. 

## Handoff Specs:

When the implementation of the handling of 'Scenario X' is finished, write a handoff doc using the '/jot:handoff-prompt' skill.

When you write the handoff, put 'MUST READ: plans/script-handling.txt' near the top, after the header of the handoff tmeplate.

## After the handoff:

Don't write a summary to me after you create the handoff, just provide the path to the handoff, as the skill specifies. 

Do not verify if the monitoring script parses the handoff correctly to trigger the next agent's session, it has already been confirmed that the monitoring script does.