---
description: Analyze codebase and generate steering documents
model: opus
allowed-tools: [Bash($WSROOT/.claude/scripts/spec-steering), Read, Write, Glob, Grep]
---

## Your task

Execute the script to analyze codebase and generate steering documents:

```bash
CC=1 $WSROOT/.claude/scripts/spec-steering
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, generate lightweight project steering documents in the steering/ directory.

Steering documents provide always-on project identity loaded at the start of every session.
They are lightweight (not exhaustive) and focus on what Claude needs to know to work effectively.

## Existing Steering Files

If files already exist (listed in existing_files), READ each one before regenerating.
Refine and improve them rather than replacing from scratch.
If a file is missing from existing_files, generate it fresh from the codebase analysis.

## Files to Generate

Generate (or refine) these files in the steering_dir shown in script output:

### product.md
Answers: What is this project? Who uses it? What problem does it solve?
Derive from: README content, package description, existing docs.
Structure:
```markdown
# Product Overview

## Purpose
[1-3 sentences: what it does and why it exists]

## Target Users
[Who uses this: developers, ops, end users, etc.]

## Key Features
- [Feature 1]
- [Feature 2]

## Constraints
- [Technical or business constraint]
```

### tech.md
Answers: What technology stack? What are the build tools and conventions?
Derive from: package.json, go.mod, pom.xml, config files, build scripts.
Structure:
```markdown
# Technology Stack

## Runtime & Language
[Language, version, runtime]

## Key Dependencies
| Package | Purpose |
|---------|---------|
| [name]  | [what it does] |

## Build & Development
[Build tools, dev commands, test commands]

## Conventions
- [Naming conventions]
- [Code style]
- [File organization patterns]
```

### structure.md
Answers: How is the codebase organized? What are the naming patterns?
Derive from: directory tree, import patterns, file naming.
Structure:
```markdown
# Project Structure

## Directory Layout
```
[ASCII tree of key directories -- not exhaustive, just the important ones]
```

## Key Directories
| Path | Purpose |
|------|---------|
| [path] | [what it contains] |

## Naming Conventions
- [File naming pattern]
- [Directory naming pattern]

## Architecture Notes
[1-3 sentences on the overall architecture pattern]
```

## Constitution (Optional)

If has_constitution is false AND the user asked to create one:
Generate constitution.md via interactive Q&A. Ask the user:
1. "What are the immutable principles for this project?" (coding standards, patterns to always use)
2. "What patterns or approaches should NEVER be used?"
3. "What quality standards must always be maintained?"
Then generate constitution.md with numbered articles.

If has_constitution is false and the user did NOT ask for a constitution:
After generating the three standard files, offer:
"Steering documents generated. Would you like to also create a constitution.md with immutable
 project principles? This gets injected into all spec generation commands as a compliance constraint."

## Constitution Content as Constraint

If constitution_content is provided, it contains existing constitution rules.
Ensure all generated steering documents are consistent with these principles.

## Output

After writing files, report:
- Which files were created/updated
- Key facts extracted for each document
- Whether to run /spec:steering again to refine further

**Examples:**
```
[OK] Generated steering documents in /path/to/steering/

  product.md  - CLI tool for managing Docker devcontainer
```

```
targets developers
  tech.md     - Node.js 20
```

```
Commander.js
```

```
YAML parsing
```

```
npm package
  structure.md - capabilities/
```

```
profiles/
```

```
src/
```

```
bin/ layout

Run /spec:steering again to refine. Add /constitution to create immutable project principles."
```

