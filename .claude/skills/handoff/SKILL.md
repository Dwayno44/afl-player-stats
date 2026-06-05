---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up. Saves to OS temp AND to the afl-player-stats repo.
argument-hint: "What will the next session focus on?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

Save the document in TWO places:
1. The OS temporary directory (e.g. `C:\Users\megan\AppData\Local\Temp\<slug>.md`) — for backward compat.
2. `C:\Users\megan\OneDrive\Documents\Claude\afl-player-stats\.claude\handoffs\<YYYY-MM-DD>-<descriptive-slug>.md` — this is the repo copy; commit it so all parallel sessions can read it.

Include a "suggested skills" section in the document, which suggests skills that the agent should invoke.

Do not duplicate content already captured in other artifacts (PRDs, plans, ADRs, issues, commits, diffs, HANDOVER.md). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
