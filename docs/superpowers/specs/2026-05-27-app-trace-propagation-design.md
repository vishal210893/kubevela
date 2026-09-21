# Trace Propagation: Webhook to Reconciler

Date: 2026-05-27
Status: Draft, awaiting review

Related:
- Issue: https://github.com/kubevela/kubevela/issues/6947 — "Enhance Application Controller with MDC-Style Logging for Better Traceability and Monitoring"
- Existing helper to reuse: `pkg/logging/logger.go` (already used by all definition validating webhooks)

## Context

Today one `kubectl apply` against a KubeVela `Application` produces logs from three actors that do not share a correlation ID. The mutating webhook, the validating webhook, and the Application controller each emit structured logs, but the API server gives each webhook a different admission UID and the controller picks up its own auto-generated ID from `monitorContext`. Following one user action through those three log streams means grepping by app name and timestamp, which falls apart under any real load.

PR #7132 added more structured fields to the controller's logs, which helps, but it kept the auto-generated `monitorContext` ID. The webhook-to-reconciler link is still broken. The PR also wrote a fresh context helper inside the application package instead of reusing `pkg/logging/logger.go`, which already exists for this exact purpose and is in use by every validating webhook in the repo.

This design closes the gap. The mutating webhook becomes the single owner of a trace ID for one user action. It stamps the ID onto the Application as an annotation. The validating webhook reads it back. The reconciler reads it from the annotation and feeds it into the existing `monitorContext` so the span/duration tracking we already have stays in place. All three actors use `pkg/logging` for ctx propagation and log field constants. No parallel system.

## Goals

- One trace ID per user action, present in mutating webhook, validating webhook, and the reconciles that follow.
- A per-reconcile span ID, produced by the `monitorContext` machinery we already have. No new ID system.
- Reuse `logging.WithRequestID`, `logging.RequestIDFrom`, `logging.NewHandlerLogger`, and the `Field*` constants. One logging package for the whole flow.
- When the webhooks are off, the reconciler still emits a usable trace ID. It does not try to write back to the object.
- No silent breakage of existing log queries. The emitted field names (`requestID`, `spanID`) stay exactly as they are.

## Non-goals

- Migrating direct `klog.Infof` call sites to structured logs. Separate slice of #6947.
- Adding `phase` and `operation` tags to every `Fork()` inside `apply.go`, `dispatcher.go`, `generator.go`, `revision.go`. Also a later slice.
- Full OpenTelemetry / W3C `traceparent` adoption. The trace ID stays a plain UUID string. Switching to a traceparent string later is a field-format change, not an architecture change.

## Design

### Life of one trace ID

1. User runs `kubectl apply -f app.yaml`.
2. API server calls the **mutating webhook**. The webhook reads `string(req.UID)`, which the API server has already minted as a UUID. If the Application does not carry `app.oam.dev/traceID`, the webhook adds it via JSON patch. The handler logger emits `requestID=<traceID>` on every line.
3. API server applies the patch, then calls the **validating webhook**. The webhook reads `app.Annotations["app.oam.dev/traceID"]`. If present, it uses that value. If absent, it falls back to `string(req.UID)`. It stores the chosen ID via `logging.WithRequestID` and emits the same `requestID` field on every log line.
4. API server persists the object. The annotation is now durable.
5. The **reconciler** picks up the event. It reads the annotation. If the annotation is missing (webhooks disabled, bootstrap apps, failurePolicy=Ignore), it mints a fresh `uuid.NewString()` in memory. It does **not** patch the annotation back. It seeds `monitorContext.NewTraceContext(ctx, traceID)` with the resolved ID, then `Fork()` produces hierarchical `spanID` values that share the trace ID at the root.

### Mental model

```
              requestID = T   spanID = mut-<uid>
mutating  ────► writes annotation  app.oam.dev/traceID = T

              requestID = T   spanID = val-<uid>
validating ──► reads annotation

              requestID = T   spanID = T.create-app-handler
reconcile #1  requestID = T   spanID = T.apply-policies        (Fork)
              requestID = T   spanID = T.gc-resourceTrackers   (Fork)

              requestID = T   spanID = T'.create-app-handler   (T' = new monitorCtx root)
reconcile #2  same trace, fresh spans
(periodic)
```

`T` is the human-visible correlation key. It travels in a single log field, `requestID`. The lifetime of `T` is "until the next user-initiated admission overwrites the annotation, or forever if no one touches it".

### Component changes

**`pkg/logging/logger.go`**

Small additions, no renames.

- Add helper `TraceIDFromObject(obj metav1.Object) (string, bool)`. Reads the annotation. Returns false if the object is nil, the annotations map is nil, or the value is empty. Generic on `metav1.Object` so non-Application callers can reuse it.
- Add helper `EnsureTraceIDAnnotation(obj metav1.Object, traceID string) (mutated bool)`. Sets the annotation only if it is currently absent or empty. Returns whether it changed anything so callers can skip the patch when no change is needed.
- Keep `FieldRequestID = "requestID"` exactly as it is. Reconciler and webhooks all log to the same field. Existing log queries do not break.

**`pkg/oam/labels.go`**

- Add `AnnotationTraceID = "app.oam.dev/traceID"`. Lives in the existing annotation home rather than `pkg/logging` so `pkg/oam` never needs to import `pkg/logging`.

**`pkg/webhook/core.oam.dev/v1beta1/application/mutating_handler.go`**

Adopt `pkg/logging` (it currently does not use it) and write the annotation.

- At the top of `Handle`, add `ctx = logging.WithRequestID(ctx, string(req.UID))` and create a handler logger via `logging.NewHandlerLogger(ctx, req, "ApplicationMutator")`.
- After the existing mutation logic, call `logging.EnsureTraceIDAnnotation(app, string(req.UID))`. If it returned true, include the annotation in the JSON patch returned to the API server.

**`pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go`**

Read the annotation first, fall back to `req.UID`.

```go
traceID := string(req.UID)
if existing, ok := logging.TraceIDFromObject(&app); ok {
    traceID = existing
}
ctx = logging.WithRequestID(ctx, traceID)
logger := logging.NewHandlerLogger(ctx, req, "ApplicationValidator")
```

Rest of the handler is untouched.

**`pkg/controller/core.oam.dev/v1beta1/application/log_context.go`**

Replace SAMurai-16's two helpers (`NewApplicationRequestContext` and `EnrichApplicationReconcileContext`) with one:

```go
func ApplicationLogContext(ctx context.Context, app *v1beta1.Application, req ctrl.Request) monitorContext.Context {
    traceID, _ := logging.TraceIDFromObject(app)
    if traceID == "" {
        traceID = uuid.NewString()
    }
    ctx = logging.WithRequestID(ctx, traceID)

    logCtx := monitorContext.NewTraceContext(ctx, traceID)
    return logCtx.AddTag(
        logging.FieldRequestID,  traceID,
        "application",           req.String(),
        "controller",            "application",
        logging.FieldName,       app.Name,
        logging.FieldNamespace,  app.Namespace,
        "app_uid",               string(app.UID),
        logging.FieldGeneration, app.Generation,
        "resource_version",      app.ResourceVersion,
        "publish_version",       app.GetAnnotations()[oam.AnnotationPublishVersion],
        "reconcile_reason",      determineApplicationReconcileReason(app),
    )
}
```

`determineApplicationReconcileReason` keeps the conservative classification SAMurai-16 already wrote: `delete`, `workflow_restart`, `unknown`. Expansion (update, periodic, manual) is out of scope here.

**`pkg/controller/core.oam.dev/v1beta1/application/application_controller.go`**

Single-line change: replace the two-step `NewApplicationRequestContext` then `EnrichApplicationReconcileContext` with one call to `ApplicationLogContext(ctx, app, req)` after the app has been fetched. The pre-fetch path (where the app is not found) still emits a minimal log with `requestID` from `req.UID` so 404 reconciles are also traceable.

### Field schema after the change

Every log line from any of the three actors contains:

| Field | Source | Example |
|---|---|---|
| `requestID` | pkg/logging | `8d3f2a04-c1a6-4e1c-9b3f-23d4f7e7c0aa` |
| `spanID` | monitorContext (controller only) | `i-1g2qtmeb.create-app-handler` |
| `handler` / `controller` | pkg/logging / monitorContext | `ApplicationMutator`, `application` |
| `name` | pkg/logging | `test-app` |
| `namespace` | pkg/logging | `default` |
| `generation` | pkg/logging | `1` |
| `app_uid` | controller only | `66604881-4812-459d-a954-53ca3205f4ee` |
| `resource_version` | controller only | `381253` |
| `publish_version` | controller only | `v1.0.0` |
| `reconcile_reason` | controller only | `unknown` |
| `user` | pkg/logging, webhooks only | `kubernetes-admin` |

### Edge cases

| Case | Behavior |
|---|---|
| Webhooks disabled (helm bootstrap, dev cluster, failurePolicy=Ignore) | Reconciler mints a fresh UUID with `uuid.NewString()` in memory. No annotation write-back. Each reconcile of the same app gets its own trace ID until the webhook comes back online. |
| User removes the annotation by hand | Mutating webhook re-mints on the next admission. Reconciler falls back to fresh UUIDs until then. |
| Controller status update | Goes via the status subresource, so the mutating webhook is not called. Annotation is preserved. Trace ID survives across reconciles. |
| Controller `metadata` patch (e.g., finalizer add) | Mutating webhook is called again. `EnsureTraceIDAnnotation` is set-if-missing, so the original trace ID stays. |
| User force-sets the annotation manually | Honored. Useful for replaying a known incident. |
| Old apps with no annotation, webhooks now enabled | First admission that touches metadata back-fills the annotation. Until then, reconciler uses fresh UUIDs. |
| Mutating webhook fails open and crashes | Annotation may be absent. Validating webhook falls back to its own `req.UID`. Reconciler later mints fresh UUIDs. No webhook-to-reconcile correlation in this run. |

### Removed from PR #7132

- `NewApplicationRequestContext` and `EnrichApplicationReconcileContext`. Their logic is absorbed into `ApplicationLogContext`.
- The hard-coded `"trace_id"` string literal. The field name now comes from `logging.FieldRequestID`.

### Tests

Two helpers, three handlers, one reconciler. So:

- `TraceIDFromObject` and `EnsureTraceIDAnnotation` get table-driven unit tests covering nil object, nil annotations map, missing key, empty value, present value.
- `ApplicationLogContext` gets unit tests for "annotation present, use it" and "annotation missing, mint one". Both paths check that the expected tag fields end up on the returned context.
- The mutating handler test cares about three scenarios: CREATE with no annotation (writes), UPDATE with no annotation (writes), UPDATE with an existing annotation (leaves it alone).
- The validating handler test is the symmetric pair: annotation present means the trace ID matches; annotation missing means it falls back to `req.UID`.
- For verification in a real cluster, the k3d loop applies an Application, captures logs from all three actors, and confirms the `requestID` value is identical end to end.

### Backward compatibility

- The emitted field `requestID` is unchanged. Existing dashboards keep working.
- The new annotation is additive. Users who do not run the webhook see no change in their object's metadata.
- `monitorContext` span semantics are unchanged.
- The PR #7132 changes that we absorb (the "Start reconcile application" log line, the `reconcile_reason` field, the conservative reason classification) are preserved.

### Rollout

This change replaces PR #7132 rather than stacking on top. The branch already carries SAMurai-16's commit, so the diff against `master` will show the absorbed and new state in one piece. Follow-up PRs that address the rest of #6947 (`klog` migration, sub-operation `Fork()` tagging, structured error helper) inherit this trace ID propagation for free.

## Locked decisions

1. Annotation key: `app.oam.dev/traceID`.
2. Annotation owner: mutating webhook only. Set-if-missing semantic.
3. `pkg/logging` field constants: keep `FieldRequestID = "requestID"`. No rename, no alias. All actors emit the same field.
4. PR #7132's `log_context.go`: absorbed and replaced.
5. Reconciler fallback when the webhook is bypassed: `uuid.NewString()` in memory, no write-back.
6. Annotation constant lives in `pkg/oam/labels.go`, not `pkg/logging`, to avoid any future import direction concern.

## Open questions

- Should the controller eventually also log the `user` field (carried via the annotation or a separate one set by the mutating webhook)? Not in scope for this design but a natural next slice for audit trails.
- If we later move to W3C `traceparent`, the field schema can carry both `requestID` and `traceparent` for a transition period. Out of scope here.
