Create a monitoring loop that checks the `plans/` folder for when the handoff document for 'Scenario X-1' is created, which documents the implementation of 'Scenario X-1'. 

The agent creating the handoff document for you hasn't finished/launched yet, so wait for the monitor to notify you that your specific 'Scenario X-1' handoff document is ready.

When the handoff document lands, check if the doc is the scenario you're being tasked with.  
Your specific scenario is 'Scenario X'.  
If the handoff doc is not meant for you, continue monitoring. 

If the handoff doc that landed is the Scenario X-1 handoff doc meant for you, read it to prepare for writing the plan for implementing handling 'Scenario X', found in `scenarios/executed/`.  Be sure to read the `MUST READ` file linked at the top of the handoff. 
Then read `~/.claude/guides/planning.md`.
Then, try to run 'Scenario X' through the `reconstruction_cli` tool to identify what the current reconstruction engine doesn't correctly catch in the 'Scenario X' JSONL. 

The specific scenario input data that produced the JSONL data you're crafting a plan for the engine to handle correctly is here: `/Users/matkatmusicllc/Programming/RevEng-worktrees/api-from-scenarios/scenarios/sX-*.txt`.  The `scenarios/executed/sX*/` folder contains the output from the run of that specific scenario, including the JSONL file and any rendered files. 

After you confirm Scenario X's data exists and you have the handoff document from the previous implementor's session for Scenario X-1, inspect the codebase using subagents to identify where the gaps are, based on the output that was generated when 'Scenario X' was run through the reconstruction_cli.

Then create the plan for 'Scenario X' so that the reconstruction_cli engine correctly handles the file change events in the JSONL.  

When the plan is finished, write a handoff doc using the '/jot:handoff-prompt' skill.

If the monitor shuts off or exits due to timing out and you haven't received the 'Scenario X' handoff document, respawn the monitor.

Include 'create handoff' in your task list for the next agent, who will implement the plan you create. 

When you write the handoff, put 'MUST READ: plans/script-handling.txt' at the top.

'X' is N



Read everything in `~/.claude/guides/`
Then, create a monitoring loop that checks the `plans/` folder for when the Handoff document for 'Scenario X' is created.  **Do not begin implementing** the plan file for 'Scenario X' when the plan lands.  Wait for the handoff document.  The plan file always lands before the handoff.

The agent creating the 'Scenario X' plan for you hasn't finished/launched yet, so wait for the monitor to notify you that your specific Handoff document is ready. 

When the handoff document lands, begin implementing the plan mentioned within for handling 'Scenario X' using the '/jot:implement' skill. The scenario you're implementing handling for is here: `/Users/matkatmusicllc/Programming/RevEng-worktrees/api-from-scenarios/scenarios/X-*.txt`.  the `scenarios/executed/X*/` folder contains the output from the run of that scenario, including the JSONL file and any rendered files. 

When the implementation of the handling of 'Scenario X' is finished, write a handoff doc using the '/jot:handoff-prompt' skill.

If the monitor shuts off or exits due to timing out and you haven't received the 'Scenario X' handoff document, respawn the monitor.

include 'create handoff' in your task list, once you start implementing the plan for 'Scenario X'.

When you write the handoff, put 'MUST READ: plans/script-handling.txt' at the top.

'X' is N
