---
description: Run parallel brainstorming sessions with persona-driven agents
model: opus
allowed-tools: [Task, Read, Write, Bash(script:spec-brainstorm), AskUserQuestion]
argument-hint: [topic] [--sessions N] [--personas N] [--keep]
---

## Arguments

- **[topic]** (optional): The topic or question to brainstorm (if omitted, brainstorms around the current spec)
- **[--sessions N]** (optional): Number of parallel brainstorming sessions (default: 3)
- **[--personas N]** (optional): Number of personas per session (default: 5)
- **[--keep]** (optional): Save each session's raw output to brainstorm-{persona}.md alongside the merged output

**IMPORTANT:** Optional flags ([--keep]) must ONLY be included when the user explicitly requests them. NEVER add these flags on your own.

## Your task

Execute the script to run parallel brainstorming sessions with persona-driven agents:

```bash
CC=1 $WSROOT/.claude/scripts/spec-brainstorm [[topic]] [[--sessions N]] [[--personas N]] [[--keep]]
```

## Output Format

The script outputs JSON when run with `CC=1`. Format the output according to this guidance:

**Instructions:** The script returned a JSON configuration for brainstorming. Follow these steps:

## Step 1: Parse Configuration

Extract the fields from the JSON:
- `topic`: The brainstorm topic (may be null -- see Step 2)
- `session_count`: Number of parallel agents to spawn
- `personas_per_session`: Number of personas each agent should embody
- `output_path`: Where to write the final merged output (null = brainstorm.md in cwd)
- `spec`: Spec name from branch association (may be null)
- `context_paths`: Array of context references from branch association
- `available_agents`: List of agent names the LLM can choose from
- `keep`: If true, save each session's raw output to individual files

## Step 2: Handle Topic

- If `topic` is provided: use it as the brainstorm topic
- If `topic` is null AND `spec` is set: read the spec documents (requirements.md, design.md, tasks.md)
  from the spec directory and brainstorm around the spec -- alternatives, extensions, gaps, and new ideas.
  Summarize the spec content as the "topic" for agents.
- If `topic` is null AND `spec` is null: ask the user for a topic using AskUserQuestion

## Step 3: Select Personas

From `available_agents`, select personas for the sessions:

- Read each agent's AGENT.md file at `$WSROOT/.claude/agents/{name}/AGENT.md` to understand what they do
- For brainstorming, prefer creative/generative personas (visionary, contrarian, provocateur, strategist,
  historian, pragmatist, optimizer, analyst, user-advocate, synthesizer) but choose based on the topic
- Select `personas_per_session` personas for each session
- When `personas_per_session` = 1: select a DIFFERENT single persona per session to maximize diversity
- When `personas_per_session` > 1: each session gets the same set of personas for internal debate

## Step 4: Spawn Parallel Brainstorming Agents

For EACH session, spawn a Task agent. Send ALL Task calls in a SINGLE message for maximum parallelism.

For each Task agent:
- `subagent_type`: "general-purpose"
- `model`: "opus"
- Do NOT use `isolation: "worktree"` -- agents return their content as text, no file writes needed

### Single Persona (personas_per_session = 1):

```
{full content from the agent's AGENT.md file}

## Your Task

Brainstorm the following topic from your persona's perspective:

**Topic:** {topic}

{if context_paths provided: "## Additional Context\n\n" + read each context path and include contents}

Produce a comprehensive markdown document (1500-3000 words) with:
1. **Perspective Summary** - Your persona's high-level take (2-3 paragraphs)
2. **Key Ideas** - 3-5 concrete ideas, each with title, description, strengths, and risks
3. **Connections** - How this relates to broader patterns and adjacent domains
4. **Recommendations** - Your top 3 ranked recommendations

Return the full markdown content as your response. Do NOT write any files.
```

### Multi-Persona Debate (personas_per_session > 1):

```
You are facilitating an internal brainstorming debate. Channel EACH of the
following personas in sequence, letting each respond to and build on the others.

{for each selected persona: full content from AGENT.md}

## Your Task

Brainstorm the following topic by cycling through each persona:

**Topic:** {topic}

{if context_paths provided: "## Additional Context\n\n" + read each context path and include contents}

For EACH persona in order:
1. Adopt that persona's cognitive lens fully
2. Generate their unique perspective (ideas, concerns, recommendations)
3. Have them respond to points raised by previous personas

Produce a synthesized document (2000-4000 words) with:
1. **Session Synthesis** - Themes from the internal debate
2. **Per-Persona Contributions** - Each persona's key ideas (labeled)
3. **Points of Agreement** - Where personas converged
4. **Points of Tension** - Where personas disagreed and why
5. **Ranked Recommendations** - Emerging from the multi-perspective debate

Return the full markdown content as your response. Do NOT write any files.
```

## Step 5: Collect Outputs

After ALL agents complete, collect the returned text from each agent.

## Step 6: Synthesize Merged Document

Write the final merged document:

```markdown
# Brainstorm: {topic}

> Generated by {N} parallel sessions, {M} personas per session.

## Executive Summary
{2-3 paragraphs synthesizing key themes across ALL sessions.
 Identify strongest ideas, important trade-offs, areas of agreement/disagreement.}

## Recommendations
{Top 5-8 ranked recommendations with persona support notes}

---

## Session 1
{full session output}

---

## Session 2
{full session output}

(repeat for all sessions)
```

## Step 7: Write Output

- If `output_path` is provided: write there (create parent dirs if needed)
- Otherwise: write to `brainstorm.md` in the current working directory
- If `keep` is true: ALSO write each session's raw output to a separate file alongside the merged
  output. Name each file `brainstorm-{persona}.md` where `{persona}` is the primary persona name
  for that session (e.g., `brainstorm-visionary.md`, `brainstorm-critic.md`). For multi-persona
  sessions, use the first persona name in the set.

## Step 8: Report

Tell the user: session count, personas used, output path, and 2-3 sentence theme overview.
If `keep` is true, also list the per-session files written.


**Examples:**
```
Spawning 3 brainstorming agents (3x5 grid)...

[Spawns 3 parallel Task agents]

All sessions complete. Writing merged output to brainstorm.md

3 sessions x 5 personas | Key themes: separation of concerns + incremental migration + plugin distribution
```

