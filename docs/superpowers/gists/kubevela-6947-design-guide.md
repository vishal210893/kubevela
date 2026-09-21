# KubeVela #6947 — MDC-Style Trace + Span Propagation: Design Guide

Issue: <https://github.com/kubevela/kubevela/issues/6947>

## 1. The two correlation IDs

| ID | Lifecycle | Source | Use |
|---|---|---|---|
| **trace ID** | Per user action — stable across **every** reconcile of the same Application until the user deletes/recreates | Stamped by the mutating webhook on admission as the annotation `app.oam.dev/traceID`. If the annotation is missing (webhook bypassed), the controller mints one. | "Show me every log line ever produced for this user-initiated change" |
| **span ID** | Per Reconcile() invocation — fresh on every entry | `uuid.NewString()` at the top of `Reconcile()` | "Show me every log line for *this one reconcile cycle*" |

These are not the same. A single user `kubectl apply` produces **one trace ID** and **many span IDs** (one per reconcile cycle the controller runs). Tools like Grafana Loki / Splunk should filter by trace ID for the user-flow view, by span ID for one reconcile attempt.

Sub-spans (via `monitorContext.Fork("apply-app-revision")`) extend the span ID with a dot-separated operation name: `<rootSpanID>.apply-app-revision`. The root UUID is what gets hoisted into the line header; the full sub-span string stays in the trailing structured field.

---

## 2. Architectural requirements

These are the contracts the implementation must meet. Order matters — each requirement enables the next.

### R1 — A single `pkg/logging` package owns field names and helpers

All field constants live in one place. Controllers and webhooks **must not** redefine field names locally. Existing constants:

```
pkg/logging.FieldRequestID   = "requestID"
pkg/logging.FieldSpanID      = "spanID"
pkg/logging.FieldName        = "name"
pkg/logging.FieldNamespace   = "namespace"
pkg/logging.FieldOperation   = "operation"
pkg/logging.FieldHandler     = "handler"
pkg/logging.FieldGeneration  = "generation"
… etc.
```

Naming convention is **camelCase** to match existing webhook log fields. Don't introduce snake_case (`trace_id`, `app_name`) — it forks the schema, breaks correlation between webhook and controller lines, and forces every downstream log query to handle both shapes.

### R2 — Both IDs propagate through **two pipes** in parallel

| Pipe | Carries | Read via | Used by |
|---|---|---|---|
| `monitorContext.Context` tag chain | trace + span | `logCtx.Info()` / `logCtx.Fork()` / `logCtx.Commit()` | Application controller telemetry (the existing `logCtx` call sites) |
| Standard `context.Context` values | trace + span | `logging.FromContext(ctx).Info(...)` | Shared helpers that take a plain `context.Context` — `pkg/utils/apply`, `pkg/controller/.../application/assemble`, `revision` helpers |

**Both pipes must be seeded.** A common mistake is stamping only the monitorContext — then helpers in `pkg/utils/apply` emit lines with only `requestID` (or nothing). If trace ID flows through std ctx but span ID doesn't, every reconcile-path line emitted via `logging.FromContext` is missing the `{spanID}` block.

### R3 — `logging.FromContext(ctx)` is the only logger entrypoint for reconcile-path helpers

No `klog.Info`, no `ctrl.LoggerFrom(ctx)`, no `log.Log.WithValues` in reconcile code paths. Reason: those bypass the `pkg/logging` context plumbing, so they emit lines without the correlation fields.

`FromContext` is the single seam where the two pipes meet — it reads requestID and spanID from std ctx and attaches them to the logr Logger that gets emitted. Anything that doesn't go through it is a future bug.

### R4 — Trace ID is **stamped once at admission**, never re-minted

The mutating webhook calls `EnsureTraceIDAnnotation(app, string(req.UID))`:

- If the annotation is absent or empty → set it to the admission UID.
- If it's present → **leave it alone**.

This is what makes the trace ID stable across reconciles. Re-minting on every reconcile (e.g., using `monitorContext.NewTraceContext(ctx, "")`'s auto-generated ID as the trace ID) defeats the entire purpose — every reconcile would correlate only with itself.

The validating webhook reads the same annotation to use as its own `requestID` field, so the admission-decision log line and the resulting reconcile lines share the same trace ID.

### R5 — Real source `file:line` is preserved

Wrapper methods on `logging.Logger` must use `logr.WithCallDepth(1)` before emitting, otherwise every line shows `logger.go:219` (the wrapper) instead of the real caller's file:line.

```go
func (l Logger) Info(msg string, keysAndValues ...interface{}) {
    l.Logger.WithCallDepth(1).Info(msg, keysAndValues...)
}
```

### R6 — Header hoisting via a `LineFormatter`

The default klog text format buries fields after the message. Operators want the trace and span IDs as visible header blocks placed at a **precise, fixed position**: immediately after the **process ID** and immediately before the `file:line]` token. This is the only position that scans cleanly at a glance because PID and file:line are the natural anchors of the existing klog header.

**Required layout:**

```
I<MMDD> <hh:mm:ss.ssssss>  <PID> {requestID} {spanID} <file>.go:<N>] "<msg>" k1=v1 …
                                  └────────┬────────┘
                                  hoisted blocks
                                  (between PID and file:line)
```

Example:

```
I0528 03:32:18.436083  25239 {trace-abc} {span-xyz} apply.go:128] "skip update" name="cov-cm" …
```

A `LineFormatter` (`io.Writer + Flush` interface) wraps the underlying output and parses each emitted klog line to do the hoist. **The same hoisting contract must hold for both production and developer modes** — there is no "dev-only" or "production-only" view of the header. Two implementations live in `pkg/logging`, one per output mode:

| Mode | Flag | Implementation | Output |
|---|---|---|---|
| Production | `--dev-logs=false` (default) | `requestIDInjector` | Plain text, header blocks hoisted |
| Developer | `--dev-logs=true` | `colorWriter` | ANSI-coloured, same header blocks hoisted (in colour) |

Both implementations must:

- Place the hoisted blocks **between PID and file:line**, in the order `{requestID} {spanID}` (never reversed, never elsewhere in the line). If only one ID is present, only that block is hoisted; the position of the present block is unchanged so log parsers can rely on the schema.
- Hoist the **UUID portion only** of `spanID` (strip the `.sub-op` suffix). The full sub-span string (e.g. `<rootUUID>.apply-app-revision`) stays in the trailing structured field so log aggregators can still filter by sub-operation name.
- Strip the trailing `requestID="…"` field from the structured fields once hoisted (de-duplicate). Keep the trailing `spanID="…"` field intact so sub-span suffixes remain queryable.
- Retain the buffered line on downstream write failure — don't drop a line because of a transient pipe error.
- Implement `Flush()` so partial buffered lines drain cleanly on `SIGTERM` / controller shutdown.
- Be wired before logging starts so the very first log line carries the contract — no "logs before formatter is ready" race.

Additionally, klog's `stderrthreshold=ERROR` writes `E*` lines through a side-channel that bypasses `os.Stdout`. Redirect `os.Stderr` through an `os.Pipe()` and feed the read end into the same formatter; otherwise `E*` lines appear unformatted and break the contract.

### R7 — Per-controller wiring is small but **must** be reused

Each controller that wants MDC-style logs follows the same pattern as the Application controller:

```
logCtx, traceID := XxxLogContext(ctx, obj, req)
ctx = logging.WithRequestID(ctx, traceID)
ctx = logging.WithSpanID(ctx, logCtx.GetID())
```

`XxxLogContext` is a small per-controller helper that knows the object's annotations. Today only `ApplicationLogContext` exists; sibling controllers (`ComponentDefinition`, `TraitDefinition`, `PolicyDefinition`, `WorkflowStepDefinition`) need their own.

---

## 3. End-to-end flow

```
┌──────────────┐  app.oam.dev/traceID
│ kubectl      │  set-if-missing on admission
│ apply        │─────────────────────────────┐
└──────┬───────┘                             │
       │                                     ▼
       │                          ┌────────────────────┐
       │                          │ Mutating Webhook   │
       │                          │ EnsureTraceID(...) │
       │                          │ emits log w/ trace │
       │                          └─────────┬──────────┘
       │                                    │
       ▼                                    ▼
┌──────────────────────────────────────────────────┐
│ kube-apiserver — stores annotation on Application│
└─────────────────────────┬────────────────────────┘
                          │ watch event
                          ▼
            ┌───────────────────────────────┐
            │ Reconcile(ctx, req)           │
            │                               │
            │ logCtx, traceID :=            │
            │    ApplicationLogContext(...) │   reads annotation
            │                               │   mints fresh spanID
            │ ctx = WithRequestID(ctx, …)   │
            │ ctx = WithSpanID(ctx, …)      │   ← BOTH pipes seeded
            └────┬───────────────────────┬──┘
                 │                       │
                 │ monitorContext        │ std context.Context
                 │                       │
                 ▼                       ▼
       logCtx.Info / Fork       logging.FromContext(ctx)
       (telemetry call sites)    (shared helpers)
                 │                       │
                 ▼                       ▼
       ┌──────────────────────────────────────┐
       │ LineFormatter — hoists IDs to header │
       │ {traceID} {spanID} file.go:N] …      │
       └──────────────────────────────────────┘
                          │
                          ▼
                  stdout / log sink
```

The two pipes meet at the `LineFormatter`: every line emitted by either pipe ends up going through the same formatter, so the output schema is identical regardless of which pipe produced the line.

---

## 4. Implementation plan — 4 phases

Each phase is self-contained and reviewable independently. Land them in order; the next depends on the previous.

### Phase 1 — Foundation in `pkg/logging`

Single source of truth for fields and context helpers.

- `Field*` constants (requestID, spanID, name, namespace, operation, handler, generation, …)
- `WithRequestID(ctx, id) / RequestIDFrom(ctx)` — std ctx round-trip with `""` as no-op
- `WithSpanID(ctx, id)  / SpanIDFrom(ctx)`  — same shape
- `FromContext(ctx)` — wraps a logr Logger and attaches both fields when present
- `Logger` wrapper with `WithCallDepth(1)` on `Info/Error/Debug/Trace`
- `TraceIDFromObject(obj)` — read `app.oam.dev/traceID` from any `metav1.Object`
- `EnsureTraceIDAnnotation(obj, id)` — set-if-missing helper for webhooks

**Acceptance:** unit tests cover round-trip, empty no-op, FromContext attaches both fields, FromContext omits them when absent.

### Phase 2 — Webhook stamps the annotation

Stable trace ID minted exactly once, at admission.

- Mutating webhook on Application: add a `handleTraceID` mutator that calls `EnsureTraceIDAnnotation(newApp, string(req.UID))`. Only mutates when the annotation is missing.
- Validating webhook: reads `TraceIDFromObject(app)` to use as its own `requestID`; falls back to `req.UID`.
- Both webhook handlers use `logging.NewHandlerLogger(ctx, req, "ApplicationValidator|Mutator")` so their log lines carry `requestID` matching the trace ID that will appear on every later reconcile.

**Acceptance:** create an Application without an annotation → the admitted object has one. Update an Application that already has one → annotation unchanged. Webhook log line and the first reconcile line share the same `requestID`.

### Phase 3 — Controller integration

The single seam where both pipes get seeded.

- `ApplicationLogContext(ctx, app, req) (monitorContext.Context, string)` lives in the application controller package. Resolves the trace ID from annotation (or mints a fresh UUID), mints a fresh per-reconcile span ID, returns the monitor context and the trace ID.
- Internally, it seeds **both** pipes:
  ```go
  ctx = logging.WithRequestID(ctx, traceID)
  ctx = logging.WithSpanID(ctx, reconcileSpanID)
  logCtx := monitorContext.NewTraceContext(ctx, reconcileSpanID).AddTag(...)
  ```
- The caller in `Reconcile()` re-seeds its own std `ctx` variable so downstream helpers (apply / assemble / revision) see both IDs through `FromContext`:
  ```go
  logCtx, traceID := ApplicationLogContext(ctx, app, req)
  ctx = logging.WithRequestID(ctx, traceID)
  ctx = logging.WithSpanID(ctx, logCtx.GetID())
  ```
- `klog.Info` call sites in the reconcile path migrate to `logging.FromContext(ctx).Info(...)` so they pick up both IDs. (Migrate a few at a time; each migration is a localized diff.)

**Acceptance:** `grep "{traceID} {spanID}.*\.go:" reconcile.log` returns every reconcile-path line — zero lines with only one block.

### Phase 4 — Header hoisting + verification

User-visible payoff.

- `LineFormatter` interface in `pkg/logging` (`io.Writer + Flush`).
- `requestIDInjector` (plain) and `colorWriter` (dev-logs) implementations — both:
  - hoist `{requestID}` between PID and `file:line]`
  - hoist `{spanID}` (UUID portion only — strip `.sub-op` suffix) after that
  - retain the buffered line on downstream write failure (don't drop on transient errors)
  - implement `Flush()` so partial lines drain at shutdown
- `cmd/core/app/server.go` wires the formatter and registers a cleanup that calls `Flush()` on `SIGTERM`. Redirect `os.Stderr` through a pipe so klog's `stderrthreshold=ERROR` side-channel goes through the same formatter (otherwise ERROR lines bypass it and appear unformatted).

**Acceptance:** live cluster run — apply a varied set of Applications (components × traits × policies × workflow steps × edge annotations) and grep the controller log:

```
grep -cE '\{[^}]+\}\s+[a-zA-Z0-9_./-]+\.go:[0-9]+\]' reconcile.log    # total
grep -cE '\{trace-[^}]+\}\s+[a-zA-Z0-9_./-]+\.go:[0-9]+\]' reconcile.log   # missing spanID
```

Second number should be **zero**.

---

## 5. Anti-patterns to avoid

1. **Defining new field constants outside `pkg/logging`** — forks the schema, breaks dashboards that filter by `requestID`/`spanID`. Always import from `pkg/logging`.
2. **Using the monitorContext's auto-generated ID as the trace ID** — per-reconcile UUID is *not* a trace ID; it's a span ID. Trace ID is per-admission and stable across reconciles.
3. **Stamping only the monitorContext, not std ctx** — leaves every `logging.FromContext(ctx)` call site without spanID.
4. **snake_case field names** (`trace_id`, `app_name`, `app_namespace`) — webhook/controller correlation breaks because the existing webhook handler logger emits camelCase.
5. **Calling `klog.Info` / `ctrl.LoggerFrom(ctx)` in reconcile-path code** — bypasses the propagation entirely.
6. **Forgetting `Flush()` on shutdown** — partial buffered lines silently lost when the controller terminates.
7. **Forgetting `WithCallDepth(1)`** — every log line shows `logger.go:219` instead of the real source file:line.

