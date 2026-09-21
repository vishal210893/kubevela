---
description: Generate or refine design document
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-design), Read, Write]
---

## Your task

Execute the script to generate or refine design document:

```bash
CC=1 $WSROOT/.claude/scripts/spec-design
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, generate or refine the spec's design.md (path shown in script output).

Read requirements.md first if it exists (reqs_content provided) to inform the design.
If design.md exists (existing_content provided), refine and expand it.
If it doesn't exist, generate a new one.

Use this structure:
1. System Architecture - Directory structure (ASCII tree), Component diagram
2. Data Flow - Numbered steps with arrows
3. Interface Specifications - APIs, environment variables, configs as tables
4. Technical Decisions - Each with: Choice, Rationale, Alternatives Considered
5. Error Handling - Table with: Scenario, Detection, Response
6. Testing Approach - Unit, integration, smoke test strategies

If constitution_content is provided, treat it as immutable project principles.
Ensure all design decisions comply with those principles.

After writing/updating, summarize key architectural decisions and suggest /spec:tasks next.

**Examples:**
```
[OK] Created design.md for spec 'feature-auth'

Key decisions:
  - Using JWT for auth tokens
  - Redis for session storage

Next: /spec:tasks
```

