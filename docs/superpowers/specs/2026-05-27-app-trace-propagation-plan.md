# Implementation Plan: Trace Propagation, Webhook to Reconciler

Date: 2026-05-27
Companion to: [2026-05-27-app-trace-propagation-design.md](./2026-05-27-app-trace-propagation-design.md)

## Source references

- GitHub issue: https://github.com/kubevela/kubevela/issues/6947
- Prior PR being replaced: https://github.com/kubevela/kubevela/pull/7132
- Existing logging helper to reuse: `pkg/logging/logger.go`
- Working branch: `app-reconcile-log-context` (already carries SAMurai-16's commit `836d597d`, which this plan rewrites)

## What this plan covers

A single PR that delivers webhook → reconciler trace propagation for the `Application` controller. The change touches three actors (mutating webhook, validating webhook, controller) and one shared package (`pkg/logging`). It replaces, rather than stacks on, PR #7132's `log_context.go`.

The plan is broken into six small phases. Each phase compiles, tests pass on its own, and the controller still runs end to end. That way the PR is reviewable in commits as well as in the final diff.

## Phases

### Phase 1: `pkg/logging` helpers (no behavior change yet)

**File**: `pkg/logging/logger.go`

Add two helpers and no constants. The shared constant comes in Phase 2 from `pkg/oam/labels.go` to avoid a `pkg/logging → pkg/oam` import dance.

- `TraceIDFromObject(obj metav1.Object) (string, bool)` — read the `app.oam.dev/traceID` annotation. Nil-safe on the object and the annotations map.
- `EnsureTraceIDAnnotation(obj metav1.Object, traceID string) (mutated bool)` — set the annotation only if absent or empty. Returns `mutated=true` only when it actually changed the map.

To keep this phase self-contained, keep a `const traceIDAnnotation = "app.oam.dev/traceID"` local to `logger.go` and switch to the shared constant in Phase 2.

**Tests** (`pkg/logging/logger_test.go`):
- `TraceIDFromObject` table-driven: nil object, nil annotations map, missing key, empty value, present value.
- `EnsureTraceIDAnnotation` table-driven: nil annotations map (initializes), absent (writes), empty (writes), present (no-op + `mutated=false`).
- All run with `-race`.

**Build gate**: `go test ./pkg/logging/... -race -cover` green.

### Phase 2: Shared annotation constant

**File**: `pkg/oam/labels.go`

Add `AnnotationTraceID = "app.oam.dev/traceID"` next to the other `app.oam.dev/...` annotations (alongside `AnnotationPublishVersion`, `AnnotationWorkflowRestart`).

**File**: `pkg/logging/logger.go`

Replace the local `traceIDAnnotation` constant from Phase 1 with `oam.AnnotationTraceID`. Import `github.com/oam-dev/kubevela/pkg/oam`. Confirm `pkg/oam` does not import `pkg/logging` first (quick grep — there is no such import today).

**Tests**: existing Phase 1 tests now run against the shared constant. No new test logic.

**Build gate**: `go build ./...` and `go test ./pkg/logging/... ./pkg/oam/... -race` green.

### Phase 3: Mutating webhook adopts `pkg/logging` and writes the annotation

**File**: `pkg/webhook/core.oam.dev/v1beta1/application/mutating_handler.go`

- At the top of `Handle`, add:
  ```go
  ctx = logging.WithRequestID(ctx, string(req.UID))
  logger := logging.NewHandlerLogger(ctx, req, "ApplicationMutator")
  ```
- After the existing mutation logic completes successfully (and `app` is decoded), call:
  ```go
  if logging.EnsureTraceIDAnnotation(app, string(req.UID)) {
      logger.Info("Stamped traceID annotation")
  }
  ```
- The annotation must land in the returned JSON patch. The mutating handler already serializes `app` to compute the patch; adding the annotation to the in-memory `app` before that serialization is enough — no manual patch construction needed.

**File**: `pkg/webhook/core.oam.dev/v1beta1/application/mutating_handler_test.go`

Three cases:
- CREATE on a brand-new Application with no annotations → patch contains the new annotation, value equals `req.UID`.
- UPDATE on an Application with no `traceID` annotation → patch contains the new annotation.
- UPDATE on an Application that already has `app.oam.dev/traceID = "existing"` → patch does NOT modify the annotation, `EnsureTraceIDAnnotation` returns false.

**Build gate**: `go test ./pkg/webhook/core.oam.dev/v1beta1/application/... -race` green.

### Phase 4: Validating webhook reads the annotation

**File**: `pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go`

Replace the single line:
```go
ctx = logging.WithRequestID(ctx, string(req.UID))
```
with:
```go
traceID := string(req.UID)
if existing, ok := logging.TraceIDFromObject(&app); ok {
    traceID = existing
}
ctx = logging.WithRequestID(ctx, traceID)
```

Order matters: the existing handler must have decoded `app` before this point so `&app` is populated. If decoding happens later in the current code, move it up.

**File**: `pkg/webhook/core.oam.dev/v1beta1/application/validating_handler_test.go`

Two cases:
- Application carries `app.oam.dev/traceID = "T"` → logger emits `requestID="T"`, not `req.UID`.
- Application has no annotation → logger emits `requestID = string(req.UID)`.

**Build gate**: `go test ./pkg/webhook/core.oam.dev/v1beta1/application/... -race` green.

### Phase 5: Replace `log_context.go` in the application controller

**File**: `pkg/controller/core.oam.dev/v1beta1/application/log_context.go`

Replace SAMurai-16's two functions with one `ApplicationLogContext`. Body matches the design doc:

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

Keep `determineApplicationReconcileReason` and its three constants (`reconcileReasonDelete`, `reconcileReasonUnknown`, `reconcileReasonWorkflowRestart`) — they survive from PR #7132 unchanged.

UUID import: `github.com/google/uuid`. Verify with `go mod why github.com/google/uuid` before assuming it is present.

**File**: `pkg/controller/core.oam.dev/v1beta1/application/log_context_test.go`

Rewrite to cover:
- App with `app.oam.dev/traceID = "T"` → returned context's request ID is `"T"`.
- App without the annotation → returned context has a non-empty UUID-shaped request ID (length, basic v4 format check).
- `determineApplicationReconcileReason`: delete, workflow_restart, unknown branches (carry over from PR #7132).

**Build gate**: `go test ./pkg/controller/core.oam.dev/v1beta1/application/... -race` green.

### Phase 6: Wire the new helper into the reconciler

**File**: `pkg/controller/core.oam.dev/v1beta1/application/application_controller.go`

Replace the two-step setup from PR #7132:
```go
logCtx := NewApplicationRequestContext(ctx, req)
...
logCtx = EnrichApplicationReconcileContext(logCtx, app)
```
with one call after the Application is fetched:
```go
logCtx := ApplicationLogContext(ctx, app, req)
```

Keep the small pre-fetch log line (the path that handles `NotFound`) using a minimal context built directly from `req.UID` so 404 reconciles are still traceable. Something like:
```go
preFetchCtx := monitorContext.NewTraceContext(ctx, string(req.UID)).AddTag(
    logging.FieldRequestID, string(req.UID),
    "controller", "application",
    "application", req.String(),
)
```

Adjust to fit the actual `NotFound` branch in `Reconcile`. Goal: every log line out of the reconciler carries `requestID`, even before the app object is loaded.

**Build gate**: `make manager` builds, `go test ./pkg/controller/core.oam.dev/v1beta1/application/... -race` green.

## Verification loop (after all six phases land locally)

Run on the existing k3d cluster (`kubevela`):

1. `make manager`, then `make image-load` (or `docker build` + `k3d image import vela-core:dev -c kubevela`).
2. `helm upgrade kubevela kubevela/vela-core -n vela-system --set image.repository=vela-core --set image.tag=dev --set logDebug=true`.
3. Tail the controller pod:
   ```bash
   kubectl -n vela-system logs -f deploy/kubevela-vela-core | tee controller.log
   ```
4. Apply a small Application:
   ```bash
   cat <<EOF | kubectl apply -f -
   apiVersion: core.oam.dev/v1beta1
   kind: Application
   metadata:
     name: trace-test
     namespace: default
   spec:
     components:
       - name: hello
         type: webservice
         properties:
           image: nginx
   EOF
   ```
5. Inspect the persisted object:
   ```bash
   kubectl get application trace-test -o jsonpath='{.metadata.annotations}' | jq .
   ```
   Confirm `app.oam.dev/traceID` is present and is a UUID.
6. Grep the log with that trace ID:
   ```bash
   grep 'requestID="<that-uuid>"' controller.log
   ```
   Expect lines from `ApplicationMutator`, `ApplicationValidator`, and `controller="application"`.
7. Edit the application (`kubectl edit application trace-test`) and confirm:
   - The annotation value is preserved (set-if-missing semantic).
   - The new admission emits the same `requestID` as the prior one, because `EnsureTraceIDAnnotation` did not overwrite.
8. Delete the application and confirm the deletion reconcile carries `reconcile_reason="delete"` and the same `requestID`.
9. Disable the webhook for a test (e.g., temporarily edit the `MutatingWebhookConfiguration` to `failurePolicy: Ignore` and remove the application rule). Create another app. Confirm the reconciler logs a freshly minted UUID `requestID` and no annotation lands on the persisted object.

## Risks and rollback

| Risk | Mitigation |
|---|---|
| Annotation write in mutating webhook silently fails (decode/encode path divergence) | Phase 3 test asserts the annotation is in the returned patch, not just on the in-memory object. |
| UUID library not vendored | Phase 5 checks `go mod why` before committing. If absent, fall back to `crypto/rand` directly. |
| Existing dashboards rely on the old `monitorContext` auto-generated ID being unique per reconcile | The new design keeps `spanID` per `Fork()`. Only the root trace value changes. Dashboards that grep `spanID=` keep working. The new `requestID` is additive. |
| Cycle risk between `pkg/oam` and `pkg/logging` | Pre-check confirms no current `pkg/oam → pkg/logging` import. If a future change introduces one, fall back to keeping the constant local in `pkg/logging`. |
| Annotation tampering by a malicious user | Trace IDs are not a security boundary. Worst case: log correlation is misleading for that one app. No authorization or PII is keyed on the trace ID. |

Rollback for any phase is a straight `git revert` of the phase commit. No data migration. No CRD changes.

## Out of scope, follow-ups

- Migrating `klog.Infof` call sites in `apply.go`, `dispatcher.go`, `generator.go`, `revision.go` to structured logs (next slice of #6947).
- Adding `phase` / `operation` tags to `Fork()` calls inside sub-operations.
- Structured error helper + `metrics.ReconcileErrorCount`.
- Webhook → reconciler propagation of `user` from `req.UserInfo.Username` (a separate annotation or audit object).
- W3C `traceparent` adoption.

## Commit / PR structure

Six commits, one per phase, in order. Each commit message follows KubeVela conventions:

1. `feat(logging): add TraceIDFromObject and EnsureTraceIDAnnotation helpers`
2. `feat(oam): add AnnotationTraceID constant`
3. `feat(webhook/application): mutating handler stamps traceID annotation`
4. `feat(webhook/application): validating handler honors traceID annotation`
5. `refactor(controller/application): replace log_context with ApplicationLogContext`
6. `feat(controller/application): wire ApplicationLogContext into Reconcile`

PR title: `feat(application): propagate traceID from admission through reconcile`

PR body should reference this plan, the design doc, issue #6947, and note that it replaces PR #7132.
