---
description: Generate or refine playback narratives document
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-playback), Read, Write]
---

## Your task

Execute the script to generate or refine playback narratives document:

```bash
CC=1 $WSROOT/.claude/scripts/spec-playback
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, generate or refine the playback.md at the spec path.

Read requirements.md, design.md, and tasks.md first if they exist to inform the narratives.
If playback.md exists (existing_content provided), refine and expand it.
If it doesn't exist, generate a new one.

Generate persona-based step-by-step narratives showing how the feature plays out end-to-end.

Document structure (in order):

# [Feature Name] Playback Narrative
[1-2 sentence summary of what this playback demonstrates]

## Overview
[2-3 paragraphs describing the feature, what it enables, and the key scenarios this playback covers]
Key value delivered:
- **For [Primary Persona Group]**: [Value they get]
- **For [Secondary Persona Group]**: [Value they get]

## Context
[Technical/business context that applies to all narratives - relevant system state, configuration, assumptions]
Key concepts and assumptions:
- [Item 1]
- [Item 2]

## Personas
**[Persona Name]** -- [One sentence describing who they are and their goal in this context]
**[Persona Name]** -- [One sentence describing who they are and their goal in this context]

## Narrative 1: [Descriptive Name]
**[Persona Name]**: [Brief statement of who performs these steps and why]
1. **[Phase Name]**
   - [Specific action with tool/UI/system name in bold]
   - [Specific action]
   - [Specific action]
2. **[Phase Name]**
   - [Specific action]
...

## Narrative 2: [Descriptive Name]
[Same structure]

## Notes
[Constraints, edge cases, or important clarifications]

Style guidance:
- Each narrative should have a distinct persona performing it
- Steps are numbered phases with bold headers; sub-actions are nested bullets
- Actions are specific and concrete (name the UI, tool, command, or API involved)
- Bold key names, versions, or identifiers within step descriptions
- 2+ narratives minimum; add Narrative 1a/1b sub-sections for complex flows with multiple sub-scenarios

After writing/updating, list the personas and narratives covered.

**Examples:**
```
[OK] Created playback.md for spec 'feature-auth'

Personas:
  - Developer (builds and publishes)
  - Admin (deploys and activates)

Narratives:
  1. Developer Setup and Build
  2. Admin Deployment and Activation
```

