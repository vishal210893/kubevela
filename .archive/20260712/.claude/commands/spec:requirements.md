---
description: Generate or refine requirements document
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-requirements), Read, Write]
---

## Your task

Execute the script to generate or refine requirements document:

```bash
CC=1 $WSROOT/.claude/scripts/spec-requirements
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, generate or refine the spec's requirements.md (path shown in script output).

If requirements.md exists (existing_content provided), refine and expand it.
If it doesn't exist, generate a new one.

Use this Kiro-style structure:

```markdown
# Requirements: [Feature Name]

## Introduction

[Brief description - 2-3 sentences about what's being built and why]

## Requirements

### Requirement 1: [Feature Area]

**User Story:** As a [role], I want [capability], so that [benefit]

#### Acceptance Criteria

1. WHEN [condition/event] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition/event] THE SYSTEM SHALL [expected behavior]
3. IF [precondition] THEN THE SYSTEM SHALL [response]

### Requirement 2: [Feature Area]

**User Story:** As a [role], I want [capability], so that [benefit]

#### Acceptance Criteria

1. WHEN [condition/event] THE SYSTEM SHALL [expected behavior]
2. WHEN [condition/event] AND [condition] THE SYSTEM SHALL [behavior]

### Requirement 3: Non-Functional Requirements

**User Story:** As a [role], I want [quality attribute], so that [benefit]

#### Acceptance Criteria

1. THE SYSTEM SHALL [performance/reliability constraint]
2. WHILE [state] THE SYSTEM SHALL [behavior constraint]

## Constraints

- [Technical or business constraint]
```

EARS Notation Patterns (REQUIRED for all acceptance criteria):
- Event-driven: WHEN [event] THE SYSTEM SHALL [action]
- Conditional: IF [condition] THEN THE SYSTEM SHALL [action]
- State-driven: WHILE [state] THE SYSTEM SHALL [action]
- Combined: WHEN [event] AND [condition] THE SYSTEM SHALL [action]
- Ubiquitous: THE SYSTEM SHALL [action]

CRITICAL:
- Use numbered lists (1. 2. 3.) for acceptance criteria, NOT tables
- Every acceptance criterion MUST use EARS notation
- Reference criteria by "Requirement N, criteria M" format
- If constitution_content is provided, treat it as immutable project principles.
  Ensure all requirements comply with those principles.

After writing/updating, report what was created and suggest /spec:design next.

**Examples:**
```
[OK] Created requirements.md for spec 'feature-auth'

Contains:
  - 3 requirements with user stories
  - 12 acceptance criteria (EARS notation)

Next: /spec:design
```

