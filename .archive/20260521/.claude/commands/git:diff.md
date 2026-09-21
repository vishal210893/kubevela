---
description: Show line-by-line changes
model: haiku
context: fork
allowed-tools: Bash($WSROOT/.claude/scripts/git-diff:*)
---

## Your task

Execute the script to show line-by-line changes:

```bash
CC=1 $WSROOT/.claude/scripts/git-diff
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Show changes clearly. For large diffs (>50 lines), summarize scope and key changes. For small diffs, show the actual changes. Make it useful for understanding what changed.

**Examples:**
```
diff --git a/src/auth.js b/src/auth.js
@@ -1
```

```
3 +10
```

```
5 @@
+  return token;"
```

```
Large diff in 3 files:
- src/auth.js: Added token validation (120 lines)
- src/api.js: Updated endpoints (45 lines)
- README.md: Updated docs (30 lines)
```

