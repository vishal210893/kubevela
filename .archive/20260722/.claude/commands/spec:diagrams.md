---
description: Generate architecture diagrams and deploy to spec steering
model: opus
allowed-tools: [Bash, Skill(diagrams), Skill(spec:steering), Read, Write, Glob, Grep]
---

## Your task

Execute the script to generate architecture diagrams and deploy to spec steering:

```bash
CC=1 $WSROOT/.claude/scripts/spec-diagrams
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** Based on the script output, orchestrate the workflow below.

## Phase 0: Ensure Steering Documents Exist (prerequisite)

Check the needs_steering field in the script output.
If needs_steering is true, the steering directory has no .md files (product.md, tech.md,
structure.md). The SpecBrowser requires these files to properly display the project.

Run the spec:steering skill first to generate them:

```
Skill("spec:steering")
```

If needs_steering is false, skip this phase.

## Phase 1: Generate Architecture Diagrams

Invoke the diagrams skill to analyze the codebase and generate PlantUML diagrams.
Use the Skill tool:

```
Skill("diagrams")
```

Follow the skill's instructions to generate diagrams under docs/architecture/.
If docs/architecture/ already has diagrams (listed in existing_diagrams), the skill will
refine or update them rather than regenerating from scratch.

## Phase 2: Build Portable Diagrams

After diagrams are generated, run the build script to create self-contained .puml files
with inlined includes:

```bash
chmod +x docs/architecture/build.sh && docs/architecture/build.sh
```

This creates portable versions in docs/architecture/.build/ that render in online tools
and CI without needing the theme file.

## Phase 3: Deploy to Spec Steering

Copy the built diagrams from docs/architecture/.build/ to the steering architecture
directory shown in steering_architecture_dir. This makes them visible in the SpecBrowser.

```bash
mkdir -p <steering_architecture_dir>
```

Copy ALL .puml files from .build/, preserving the subdirectory structure:

```bash
cd docs/architecture/.build && find . -name '*.puml' | while read f; do
  mkdir -p "<steering_architecture_dir>/$(dirname "$f")"
  cp "$f" "<steering_architecture_dir>/$f"
done
```

Also copy the manifest.yaml if it exists:

```bash
[ -f docs/architecture/manifest.yaml ] && cp docs/architecture/manifest.yaml <steering_architecture_dir>/manifest.yaml
```

Replace <steering_architecture_dir> with the actual path from the script output.

## Output

After all phases complete, report:
- Number of diagrams generated
- Number of files deployed to steering
- The steering architecture directory path
- Remind user to restart SpecBrowser (dev sb) to see the diagrams

**Examples:**
```
[OK] Architecture diagrams generated and deployed

  Phase 1: Generated 7 diagrams in docs/architecture/
  Phase 2: Built 7 portable .puml files
  Phase 3: Deployed to /path/to/steering/architecture/

Restart SpecBrowser to view: dev sb
```

