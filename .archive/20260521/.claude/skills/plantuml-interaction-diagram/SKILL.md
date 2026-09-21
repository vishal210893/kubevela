---
name: plantuml-interaction-diagram
description: This skill should be used when the user asks to "create a sequence diagram", "create an interaction diagram", "PlantUML sequence diagram", "diagram a flow", "visualize communication between services", "show how components interact", or mentions creating PlantUML interaction or sequence diagrams. Guides an interactive workflow to gather requirements, identify participants, map interactions, generate well-structured PlantUML code, write the output file, and iterate on the result.
version: 1.0.0
---

# PlantUML Interaction Diagram Generator

This skill produces PlantUML sequence/interaction diagrams through a guided, interactive workflow. It covers participant discovery, message flow mapping, fragment selection, styling, file output, and iterative refinement.

## Workflow Overview

The diagram creation process follows five phases executed in order. Each phase builds on the output of the previous one. Do not skip phases unless the user has already provided all required information up front.

| Phase | Purpose | Key Output |
|-------|---------|------------|
| 1. Gather Requirements | Understand what to diagram | Flow description, scope, detail level |
| 2. Identify Participants | Determine who/what communicates | Typed participant list |
| 3. Map Interactions | Define the message flow | Ordered message sequence with fragments |
| 4. Generate PlantUML | Produce the `.puml` source | Complete, valid PlantUML code |
| 5. Write and Iterate | Save file, refine as needed | Final `.puml` file on disk |

## Phase 1: Gather Requirements

Begin by asking the user concise, targeted questions. Do not ask all questions at once — start with the most important and follow up as needed.

### Essential Questions (ask first)

- What system or flow needs to be diagrammed? (e.g., "user login flow", "order checkout", "webhook processing pipeline")
- What level of detail is needed: **overview** (happy path only, minimal notes) or **detailed** (error handling, alt paths, timing notes)?

### Follow-Up Questions (ask if not already clear)

- Are there specific error scenarios or alternate paths to include?
- Should the diagram show return messages explicitly, or keep them implicit?
- Is there a preferred output file path, or use the current directory?

If the user provides a thorough description up front, extract answers from it rather than re-asking. Confirm understanding before proceeding.

## Phase 2: Identify Participants

Determine every participant in the interaction and assign the most appropriate PlantUML type.

### Participant Type Selection Guide

| Type | When to Use | Visual |
|------|-------------|--------|
| `actor` | Human user or external human role | Stick figure |
| `participant` | Generic service, module, or component | Box |
| `boundary` | System boundary, API gateway, controller | Half-box |
| `control` | Orchestrator, workflow engine, mediator | Circle-arrow |
| `entity` | Domain object, business entity, model | Circle-line |
| `database` | Database, data store, cache (Redis, S3) | Cylinder |
| `queue` | Message queue, event bus (Kafka, SQS, RabbitMQ) | Queue shape |
| `collections` | Collection of similar items, pool of workers | Stacked boxes |

### Participant Organization

- Group related participants using `box "Group Name" #Color ... end box` to represent logical layers (e.g., "Frontend", "Backend Services", "External Systems").
- Order participants left-to-right following the natural flow of data: initiator on the left, terminal systems on the right.
- Use short aliases for readability: `participant "Authentication Service" as Auth`.
- Apply distinct colors to boxes representing different architectural tiers.

Confirm the participant list with the user before proceeding to Phase 3.

## Phase 3: Map Interactions

Build the sequence of messages step by step.

### Message Flow Construction

1. Start with the triggering event (the first message from the initiating actor or system).
2. For each message, determine:
   - **Direction**: Who sends to whom?
   - **Synchronous or asynchronous**: Sync uses `->`, async uses `->>` or `-->`.
   - **Message label**: Concise verb-noun description (e.g., `POST /login`, `validateToken()`, `emit OrderCreated`).
   - **Return value**: Include explicit returns for sync calls using `-->` or the `return` keyword.
3. Add activation bars (`activate`/`deactivate` or `++`/`--` shortcuts) to show when a participant is processing.
4. Identify fragments needed:
   - `alt/else` for conditional branching (e.g., valid vs invalid credentials)
   - `opt` for optional steps (e.g., "if MFA enabled")
   - `loop` for repeated operations (e.g., "for each item in cart")
   - `par` for parallel operations (e.g., "send email AND update cache simultaneously")
   - `break` for early termination (e.g., "if rate limit exceeded, abort")
   - `critical` for atomic operations (e.g., "database transaction")
5. Add notes (`note left/right of`, `note over`) where clarification helps — protocol details, timeout values, business rules.
6. Insert dividers (`== Phase Name ==`) to separate logical phases (e.g., "== Authentication ==", "== Authorization ==").

### Complexity Guidelines

| Detail Level | Fragments | Notes | Returns | Activation |
|-------------|-----------|-------|---------|------------|
| Overview | None or 1 alt | Minimal | Implicit | Optional |
| Detailed | All relevant | Generous | Explicit | Required |

## Phase 4: Generate PlantUML

Assemble the final PlantUML code following this structure. Refer to `references/syntax.md` for comprehensive syntax details and `references/patterns.md` for common flow patterns.

### Standard Diagram Structure

Every generated diagram follows this ordering:

```
@startuml <diagram-name>
  1. Theme and skin parameters
  2. Title
  3. Participant declarations (with boxes)
  4. Autonumber (if detailed level)
  5. Interaction messages with fragments
  6. Notes
  7. Legend (if needed)
@enduml
```

### Generation Rules

- Always begin with `@startuml` and a descriptive diagram name (kebab-case).
- Apply `!theme plain` for clean, professional output unless the user requests otherwise.
- Declare all participants explicitly at the top — never rely on implicit declaration from first usage.
- Use `autonumber` for detailed diagrams to make message sequences easy to reference in discussion.
- Keep message labels concise: prefer `POST /api/login` over `The user sends a POST request to the login endpoint`.
- Use color sparingly and consistently: one color per logical group, not per message.
- Add a `legend` block at the bottom when the diagram uses non-obvious conventions.
- Ensure every `activate` has a matching `deactivate` (or use `++`/`--` shorthand for correctness).
- Ensure every fragment (`alt`, `opt`, `loop`, `par`, `break`, `critical`) has a matching `end`.

### Skinparam Defaults

Apply these unless the user specifies otherwise:

```plantuml
skinparam sequence {
  ArrowColor #333333
  LifeLineBorderColor #333333
  ParticipantBorderColor #333333
  ParticipantBackgroundColor #FEFECE
  ActorBorderColor #333333
  ActorBackgroundColor #FEFECE
  DatabaseBackgroundColor #E8F5E9
  QueueBackgroundColor #E3F2FD
}
skinparam noteBorderColor #999999
skinparam noteBackgroundColor #FFFFCC
```

## Phase 5: Write and Iterate

### File Output

- Ask the user for the target file path. If none specified, default to `./<diagram-name>.puml` in the current working directory.
- Write the complete `.puml` file to disk.
- Inform the user of the file path and how to render it.

### Rendering Options

Mention these rendering methods after writing the file:

1. **Online**: Paste source at `https://www.plantuml.com/plantuml/uml/`
2. **VS Code**: Install the PlantUML extension for live preview
3. **CLI**: `java -jar plantuml.jar <file>.puml` generates PNG

### Iteration

After delivering the initial diagram, offer to refine it. Common refinements include:

- Adding or removing participants
- Adding error/alternate paths with `alt`/`else` fragments
- Adjusting detail level (adding/removing activation bars, notes, autonumber)
- Splitting a large diagram into multiple pages with `newpage`
- Grouping participants differently
- Changing styling or colors

When iterating, re-read the existing `.puml` file, apply the requested changes, and write the updated version back. Do not regenerate from scratch unless the user requests a complete redesign.

## Reference Material

For comprehensive syntax details beyond what is covered in this workflow, read the following reference files as needed:

- **`references/syntax.md`** — Complete PlantUML sequence diagram syntax covering all participant types, arrow types, activation, fragments, notes, layout controls, styling, and advanced features.
- **`references/patterns.md`** — Common interaction patterns with full PlantUML source for authentication flows, REST API CRUD operations, microservice choreography, event-driven architectures, saga patterns, circuit breakers, and WebSocket communication.

## Example Files

The `examples/` directory contains complete, working `.puml` files demonstrating different complexity levels:

- **`examples/basic-api-request.puml`** — Simple REST API request/response (overview level, no fragments)
- **`examples/auth-flow-detailed.puml`** — Multi-step authentication with MFA, error handling, token refresh (detailed level, uses alt/opt/loop fragments)
- **`examples/microservice-event-driven.puml`** — Asynchronous event-driven flow across multiple services with queues and parallel processing

Use these as starting points or as references when assembling a new diagram.
