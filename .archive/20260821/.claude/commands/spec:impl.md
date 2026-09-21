---
description: Execute tasks from the spec's tasks.md
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-impl), Read, Write, Edit, Glob, Grep, Bash]
argument-hint: [task-ids]
---

## Arguments

- **[task-ids]** (optional): Task IDs to implement: single (1.1), comma-separated (1.1,1.2), range (1.1-1.5), or empty for next unchecked task

## Your task

Execute the script to execute tasks from the spec's tasks.md:

```bash
CC=1 $WSROOT/.claude/scripts/spec-impl [task-ids]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, implement the specified task(s) from the spec's tasks.md.

For each task in the "tasks" array:
1. Use "title", "metadata.File", "metadata.Change", "metadata.Outcome", and "metadata.Context"
   to understand exactly what to build.
2. Read the file(s) referenced in "metadata.File" before making changes.
3. Implement the change described in "metadata.Change", guided by "metadata.Outcome" and
   "metadata.Context". Follow TDD: write or update tests first when the change involves
   testable code.
4. After completing the implementation, update the task checkbox in "tasks_file":
   Change `- [ ] **<id>**` to `- [x] **<id>**` using the Edit tool.
   If the task line uses a "Task" prefix like `- [ ] **Task 1.1**:`, update that form too.

If "all_complete" is true: report that all tasks in the spec are complete.

If "blocked_tasks" is non-empty: explain that those tasks cannot run because their
dependencies must be completed first. List the unmet dependency IDs and what they require.

If "not_found" is non-empty: report those task IDs were not found in tasks.md.

Use "reqs_content" and "design_content" for additional context on requirements and design
intent when needed.

After completing all tasks in the current batch:
- If mode is "next": run `CC=1 $WSROOT/.claude/scripts/spec-impl` (no args) to get the
  next task and continue implementing until all_complete is true. Do NOT stop between tasks —
  keep looping until the entire spec is complete, then summarize all changes made.
- If mode is "specific": briefly summarize what was changed (files modified).

**Examples:**
```
[OK] Implemented task 1.1: Add parse_tasks() to speclib.py

Changes:
  capabilities/spec/src/claude/scripts/lib/speclib.py

Checkbox updated: 1.1 marked [x]

Next: 1.2 - Add check_dependencies() to speclib.py
  Run: /spec:impl 1.2
```

