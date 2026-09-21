# Consult Injected Spec/Ctx Content Before Filesystem Search

**When to use this rule**: Whenever the user references a topic, file, table,
row, scenario, section, or term that may be covered by spec or context
documents already loaded at session start.

## Problem

The SessionStart hook injects steering docs, the associated spec's files, and
any subsystem context docs into the conversation. When the user asks about a
topic ("the playback first row", "the foo table", "scenario X"), the answer
is often already in that injected content -- but it is easy to skip past it
and reach for `find`, `grep`, `Read`, or an `Explore` agent instead, which
wastes tokens and can return a "not found" answer when the content was right
there in context.

## Rule

Before running filesystem or shell searches for a user-referenced topic:

1. Scan the injected SessionStart content first (steering docs, the associated
   spec's `requirements.md`/`design.md`/`tasks.md`/`playback.md`/etc., and any
   loaded ctx documents).
2. Only fall back to `Read`, `grep`, `find`, or `Explore` when the injected
   content does not cover the topic, or when the user explicitly asks for a
   fresh filesystem search.
3. If a filename the user mentioned (e.g. `playback.md`) does not exist on
   disk but matching content is present in an injected ctx (e.g. a `# Playback`
   section in `cap-admin/playback.md`), use the injected content rather than
   reporting the file as missing.

## Why

Injected ctx is the curated, branch-scoped knowledge base. Skipping it forces
the user to repeat themselves and produces wrong answers when the content is
already in context. The cost of one extra context scan is far lower than the
cost of a misleading "no such file" reply.
