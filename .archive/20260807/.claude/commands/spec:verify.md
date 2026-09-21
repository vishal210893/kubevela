---
description: Verify implementation against specification
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-verify), Read, Glob, Grep]
---

## Your task

Execute the script to verify implementation against specification:

```bash
CC=1 $WSROOT/.claude/scripts/spec-verify
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Perform multi-dimensional specification verification using the gathered context.

Analyze four dimensions in order:

1. TASK COMPLETION
   - Use tasks_summary from script output (completed/total counts, incomplete items)
   - List each incomplete task
   - Flag CRITICAL if any incomplete task is a blocker for other tasks (check BlockedBy references)
   - Flag INFO for incomplete tasks that don't block anything

2. REQUIREMENTS TRACEABILITY
   - Read each EARS criterion from requirements content (look for WHEN/IF/WHILE/THE SYSTEM SHALL patterns)
   - For each requirement, scan changed_files and diff_content for evidence of implementation
   - Flag WARNING for requirements with no implementation evidence in changed files
   - Flag CRITICAL for requirements explicitly marked as critical/P0 with no implementation
   - If no requirements.md exists, skip this dimension and note it

3. DESIGN COHERENCE
   - Read architecture decisions, technology choices, and file structure expectations from design content
   - Compare against changed_files and file_tree for consistency
   - Flag WARNING for design decisions not reflected in code (e.g., design says "Redis" but no Redis usage found)
   - If no design.md exists, skip this dimension and note it

4. CROSS-ARTIFACT CONSISTENCY
   - Check that requirements reference tasks and vice versa
   - Check that design decisions are reflected in task structure
   - Flag WARNING for orphaned requirements (no matching task) or orphaned tasks (no requirement backing)
   - If any doc is missing, note which cross-references cannot be checked

Severity levels:
  CRITICAL - Blocks progress or indicates missing core functionality
  WARNING - Partial implementation, design drift, or gaps that should be addressed
  INFO - Suggestions, minor inconsistencies, potential improvements

Output format (use exactly this structure):

```
# Verification Report: <spec_name>

## Summary
- Tasks: N/M complete (K remaining)
- Requirements traceability: N/M verified (K findings)
- Design coherence: N findings
- Cross-artifact consistency: PASS/N findings

## Findings

### CRITICAL: <identifier> - <title>
<description of the gap with specific evidence>

### WARNING: <identifier> - <title>
<description of the gap with specific evidence>

### INFO: <identifier> - <title>
<description>
```

If all dimensions pass with no findings, output:
```
# Verification Report: <spec_name>

## Summary
- Tasks: M/M complete
- Requirements traceability: PASS
- Design coherence: PASS
- Cross-artifact consistency: PASS

All checks passed. Implementation aligns with specification.
```

Be specific in findings - quote the relevant requirement text, design decision, or task description.
Reference file paths from changed_files when noting missing implementations.

**Examples:**
```
# Verification Report: auth-feature

## Summary
- Tasks: 7/10 complete (3 remaining)
- Requirements traceability: 8/10 verified (2 WARNINGS)
- Design coherence: 1 WARNING
- Cross-artifact consistency: PASS

## Findings

### WARNING: REQ-003 (Rate Limiting) - No implementation found
Requirement: \"WHEN client exceeds 100 requests/minute THE SYSTEM SHALL return HTTP 429\"
No matching implementation detected in changed files.

### WARNING: Design Decision \"Redis for session storage\" - Not reflected
design.md specifies Redis. Implementation uses in-memory storage.
```

