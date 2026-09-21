---
description: Interactive Q&A to refine spec
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-interview), Read, Write, AskUserQuestion]
---

## Your task

Execute the script to interactive q&a to refine spec:

```bash
CC=1 $WSROOT/.claude/scripts/spec-interview
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Analyze the spec documents provided in the script output for gaps, ambiguities, and inconsistencies.

Using AskUserQuestion, ask 1-4 targeted questions to clarify:
- Missing requirements or acceptance criteria
- Unclear technical decisions
- Ambiguous interfaces or data flow
- Incomplete implementation tasks

Based on the answers, update the relevant spec documents.
Iterate if needed until the spec is complete and clear.

IMPORTANT: When updating requirements.md, ALL acceptance criteria MUST use EARS notation:
- WHEN [event] THE SYSTEM SHALL [action]
- IF [condition] THEN THE SYSTEM SHALL [action]
- WHILE [state] THE SYSTEM SHALL [action]
- WHEN [event] AND [condition] THE SYSTEM SHALL [action]
- THE SYSTEM SHALL [action]  (ubiquitous, use sparingly)

Use numbered lists (1. 2. 3.) for acceptance criteria, never checkboxes.
If existing criteria don't use EARS notation, convert them during updates.

After each round of questions, summarize what was clarified and what documents were updated.

**Examples:**
```
Analyzing spec 'feature-auth'...

Found 3 areas needing clarification:

1. Authentication method not specified
2. Token expiration policy unclear
3. Missing error handling scenarios

[Asks questions via AskUserQuestion]

Updated:
  - requirements.md: Added AC-1.4 for token expiration
  - design.md: Added error handling table
```

