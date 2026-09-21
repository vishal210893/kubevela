---
description: Swarm review of current spec with persona-driven agents
model: opus
allowed-tools: [Task, Read, Write, Bash(script:spec-swarm)]
argument-hint: [focus] [--sessions N] [--personas N] [--keep]
---

## Arguments

- **[focus]** (optional): Optional focus area for the review (free-form text, e.g. 'design', 'security', 'error handling')
- **[--sessions N]** (optional): Number of parallel review sessions (default: 3)
- **[--personas N]** (optional): Number of personas per session (default: 5)
- **[--keep]** (optional): Save each session's raw output to swarm-{persona}.md alongside the merged output

**IMPORTANT:** Optional flags ([--keep]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to swarm review of current spec with persona-driven agents:

```bash
CC=1 $WSROOT/.claude/scripts/spec-swarm [[focus]] [[--sessions N]] [[--personas N]] [[--keep]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** The script returned a JSON configuration for a spec swarm review. Follow these steps:

## Step 1: Parse Configuration

Extract the fields from the JSON:
- `session_count`: Number of parallel agents to spawn
- `personas_per_session`: Number of personas each agent should embody
- `focus`: Optional focus area for the review (may be null)
- `spec_path`: Path to the spec directory
- `spec_documents`: Map of document type -> path (only includes files that exist)
- `available_agents`: List of agent names the LLM can choose from
- `keep`: If true, save each session's raw output to individual files

## Step 2: Read Spec Documents

Read ALL spec documents listed in `spec_documents` using the Read tool. These will be included
in each agent's prompt so they can review the full spec.

## Step 3: Select Personas

From `available_agents`, select personas for the review sessions:

- Read each agent's AGENT.md file at `$WSROOT/.claude/agents/{name}/AGENT.md` to understand what they do
- For spec review, prefer analytical/review personas (chief-architect, security-reviewer, devils-advocate,
  testability-reviewer, delivery-manager, chief-programmer, ops-reviewer, requirements-analyst, simplifier,
  api-designer) but choose based on the spec content and focus area
- If `focus` is set, weight persona selection toward that area (e.g., "security" -> security-reviewer,
  "design" -> chief-architect, architect)
- Select `personas_per_session` personas for each session
- When `personas_per_session` = 1: select a DIFFERENT single persona per session to maximize diversity
- When `personas_per_session` > 1: each session gets the same set of personas for internal debate

## Step 4: Spawn Parallel Review Agents

For EACH session, spawn a Task agent. Send ALL Task calls in a SINGLE message for maximum parallelism.

For each Task agent:
- `subagent_type`: "general-purpose"
- `model`: "opus"
- Do NOT use `isolation: "worktree"` -- agents return their content as text, no file writes needed

### Single Persona (personas_per_session = 1):

```
{full content from the agent's AGENT.md file}

## Your Task

Review the following specification from your persona's perspective. Evaluate
completeness, identify gaps, find risks, and suggest improvements. Be specific --
reference exact sections and propose concrete fixes.

{if focus: "**Review Focus:** " + focus + "\n\nConcentrate your review on this area while still noting critical issues elsewhere.\n"}

{for each spec document: "### " + document_name + "\n\n" + document_contents}

Produce a review document with:
1. **Critical Issues** - Problems that must be fixed
2. **Warnings** - Potential concerns worth investigating
3. **Suggestions** - Improvements that would strengthen the spec
4. **Overall Assessment** - Your persona's verdict

Return the full markdown content as your response. Do NOT write any files.
```

### Multi-Persona Debate (personas_per_session > 1):

```
You are facilitating an internal spec review debate. Channel EACH of the
following personas in sequence, letting each respond to and build on the others.

{for each selected persona: full content from AGENT.md}

## Your Task

Review the following specification by cycling through each persona:

{if focus: "**Review Focus:** " + focus + "\n\nConcentrate the review on this area while still noting critical issues elsewhere.\n"}

{for each spec document: "### " + document_name + "\n\n" + document_contents}

For EACH persona in order:
1. Adopt that persona's review lens fully
2. Identify issues, risks, and gaps from their perspective
3. Respond to findings raised by previous personas

Produce a synthesized review (2000-4000 words) with:
1. **Critical Issues** - Problems multiple personas flagged
2. **Warnings** - Concerns from at least one persona
3. **Points of Agreement** - Where reviewers converged
4. **Points of Tension** - Where reviewers disagreed
5. **Ranked Recommendations** - For improving the spec

Return the full markdown content as your response. Do NOT write any files.
```

## Step 5: Collect Outputs

After ALL agents complete, collect the returned text from each agent.

## Step 6: Synthesize Merged Review

Write the final merged review document:

```markdown
# Spec Review: {spec name}

> Reviewed by {N} parallel sessions, {M} personas per session.
{if focus: "> Focus: " + focus}

## Critical Issues
{Issues found across multiple sessions, deduplicated and ranked by severity}

## Warnings
{Concerns worth investigating, with session references}

## Suggestions
{Improvements to strengthen the spec}

---

## Session 1 Review
{full session output}

---

## Session 2 Review
{full session output}

(repeat for all sessions)
```

## Step 7: Write Output

Write the merged review to the `output_path` from the JSON config.
If `keep` is true: ALSO write each session's raw output to a separate file alongside the merged
output. Name each file `swarm-{persona}.md` where `{persona}` is the primary persona name
for that session (e.g., `swarm-chief-architect.md`, `swarm-security-reviewer.md`). For
multi-persona sessions, use the first persona name in the set.

## Step 8: Report

Tell the user: session count, personas used, output path, and 2-3 sentence summary of critical findings.
If `keep` is true, also list the per-session files written.


**Examples:**
```
Spawning 3 review agents (3x5 grid)...

[Spawns 3 parallel Task agents]

All sessions complete. Writing merged review to swarm.md

3 sessions x 5 personas | Critical: 2 issues found across sessions | 5 warnings | 8 suggestions
```

