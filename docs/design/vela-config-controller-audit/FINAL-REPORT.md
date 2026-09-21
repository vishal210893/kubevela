# Vela Config controller verification report

> Audit report and reproducible evidence for issue #7105.

Date: 2026-08-13  
Branch: `issue-7105` (`anishbista60/issue-7105`, plus the local design-document commit)  
Cluster: `k3d-kubevela`  
Test namespace: `cfg-audit-7105`

## 1. Executive summary

**Verdict: NOT READY.**

The declarative path works for the basic single-Secret case. ConfigTemplate
schema extraction works, as do inline and Secret-backed properties, CRD-first
template lookup, Secret ownership, drift repair, dependency watches, recovery
after missing dependencies, and garbage collection when a Config is deleted.

It is not ready to replace the imperative implementation described in issue
#7105. These problems block it:

1. A sensitive template still accepts inline properties. The controller stores
   the secret value in the Config CR and materializes it, which contradicts the
   issue's explicit security requirement.
2. The ConfigTemplate webhook deliberately admits invalid CUE, and the Config
   webhook deliberately admits both `properties` and `propertiesFrom`. These
   objects fail only after reconciliation, contrary to the issue's admission
   contract.
3. JSON integer properties become `float64` in the controller and fail CUE
   integer validation, while the imperative path accepts the same value.
4. The controller supports only `template.output`. It does not support
   `template.outputs` or expanded writers. The CLI fallback creates legacy
   resources that the CRD-mode list and delete commands cannot later see or
   manage.
5. The `create-config` workflow provider still calls the imperative factory and
   creates a legacy Secret instead of a Config CR.
6. Changing a rendered Secret name leaves the old Secret behind until the Config
   is deleted.
7. The CLI puts sensitive input in an unowned companion Secret and leaves that
   Secret behind when the Config is deleted.
8. A controller-created Secret without an explicit type becomes `Opaque`; the
   imperative path synthesizes `/<template-name>`.

The detailed 48-case ledger is in [RESULTS.md](RESULTS.md). The test plan written
before execution is in [TEST-MATRIX.md](TEST-MATRIX.md).

## 2. Code review findings

### Correct implementation areas

- The ConfigTemplate reconciler parses CUE, extracts the parameter schema, and
  reports stable Available/Error status.
- Config lookup is CRD-first with a legacy `config-template-*` ConfigMap
  fallback. A CRD correctly takes precedence.
- The reconciler forces output into the Config namespace, so a template cannot
  write a Secret into another namespace.
- The Config owns its output Secrets. The reconciler refuses to adopt or
  overwrite an existing unowned Secret.
- Reconciliation is idempotent after convergence. Manual output deletion and
  drift are repaired.
- ConfigTemplate, legacy template ConfigMap, and input Secret changes enqueue
  dependent Config objects, and dependency repair recovers failed Configs.
- Status update conflict retries are present, and normal status writes do not
  create a permanent reconciliation loop.

### CVC-01: sensitive inline data is accepted

- Severity: P0 / Critical
- File: `pkg/webhook/config.oam.dev/v1alpha1/config/validating_handler.go`
- Function: `ValidatingHandler.Handle`
- Problem: neither the API schema, webhook, nor reconciler rejects inline
  `spec.properties` when the resolved template is sensitive.
- Why it matters: credentials are persisted in a normal custom resource and can
  be read by anyone with Config read permission. This directly contradicts the
  issue requirement that sensitive values must use `propertiesFrom` and never
  enter the CRD.
- Evidence: CFG-035 stored the placeholder token verbatim in the Config and
  reached Available.
- Recommendation: resolve the template at admission and reject inline
  properties for sensitive templates. Repeat the check in reconciliation as a
  defense in depth. Consider CEL where feasible, but template sensitivity needs
  a lookup to determine whether the template is sensitive.

### CVC-02: required admission validation is missing

- Severity: P1 / High
- Files: both validating handlers under
  `pkg/webhook/config.oam.dev/v1alpha1/`
- Problem: ConfigTemplate validation only decodes and returns allowed. Config
  validation returns allowed when both property sources are set.
- Evidence: the corresponding unit tests explicitly expect admission, and live
  CFG-003/CFG-034 objects were admitted and later moved to Error.
- Recommendation: reject malformed CUE, schema extraction failures, and mutually
  exclusive property sources at admission. Change the tests to assert denial.

### CVC-03: decoding corrupts integer values

- Severity: P1 / High
- File: `pkg/controller/config.oam.dev/v1alpha1/config/config_controller.go`
- Function: `resolveProperties`
- Problem: unmarshalling `runtime.RawExtension` into
  `map[string]interface{}` converts JSON numbers to `float64`. CUE then rejects
  values for integer parameters.
- Evidence: CFG-030. `count=3` succeeded through imperative dry-run, but the
  equivalent Config CR became Error. The CLI still printed "applied
  successfully."
- Recommendation: use a number-preserving JSON decoder (`UseNumber`) followed
  by an intentional numeric conversion, or use the same canonical conversion
  path in webhook, reconciler, and imperative factory.

### CVC-04: old rendered outputs are not removed

- Severity: P1 / High
- File: `pkg/controller/config.oam.dev/v1alpha1/config/config_controller.go`
- Functions: `renderSecret`, `applySecret`
- Problem: when a Config/template update changes `metadata.name` in the rendered
  Secret, the reconciler creates the new Secret and overwrites
  `status.secretRef`; it does not delete the previously controlled Secret.
- Evidence: CFG-024 left both `audit-renamed-one` and `audit-renamed-two`.
- Recommendation: compare the prior status reference and delete only an old
  Secret whose controller owner is the current Config, or make output identity
  immutable and reject the change.

### CVC-05: partial `outputs` support breaks CLI management

- Severity: P0 / Blocking feature gap
- File: `references/cli/config.go`
- Functions: create, list, and delete commands
- Problem: create detects unsupported controller features and falls back to
  legacy storage. Once Config CRDs exist, list and delete use only Config CRs,
  so the newly created fallback config is invisible and undeletable through the
  CLI. Controller reconciliation itself ignores `template.outputs` and expanded
  writers.
- Evidence: CFG-038/CFG-039 created the legacy output and extra ConfigMap, but
  `vela config list` omitted it and `vela config delete` reported not found.
- Recommendation: implement true dual-read and dual-delete during the
  transition. Either implement outputs/writers in the reconciler or document
  and consistently manage the fallback objects.

### CVC-06: the sensitive companion Secret leaks

- Severity: P0 / Critical
- File: `references/cli/config_crd.go`
- Function: `createConfigCRD`
- Problem: `<config>-properties` is created before the Config without an owner
  reference, tracking label, or cleanup path. Config deletion leaves the
  credential behind. A later Config creation failure also leaves it behind.
- Evidence: CFG-040.
- Recommendation: use a deterministic ownership/cleanup design. Because an
  owner reference cannot safely be installed before the Config UID exists,
  create the Config first, then create/update the companion Secret with the
  Config as controller owner, and handle partial failures. Refuse to overwrite
  an unrelated pre-existing companion Secret.

### CVC-07: the workflow path still uses legacy storage

- Severity: P0 / Blocking feature gap
- File: `pkg/workflow/providers/config/config.go`
- Function: `CreateConfig`
- Problem: it still calls `ParseConfig` and `CreateOrUpdateConfig`, producing
  legacy Secret storage instead of a Config CR.
- Evidence: CFG-041 completed successfully but no Config CR existed.
- Recommendation: switch workflow creation to the shared CRD creation service,
  including sensitive-property handling and a compatibility fallback only when
  the Config CRD is unavailable.

### CVC-08: the default Secret type does not match

- Severity: P1 / Medium-High
- Files: new Config reconciler versus `pkg/config/factory.go`
- Problem: the imperative factory synthesizes `/<template-name>` when the
  template omits Secret type. The controller leaves type empty, so Kubernetes
  stores it as `Opaque`.
- Evidence: CFG-037 and CFG-046.
- Recommendation: share the output-normalization helper with the imperative
  factory and add an exact-object parity test.

### CVC-09: the CLI reports success too early

- Severity: P1 / High UX correctness
- File: `references/cli/config.go`
- Function: `NewCreateConfigCommand`
- Problem: the command returns success immediately after CR creation. A known
  invalid integer Config therefore prints success and later becomes Error.
- Recommendation: either wait for the observed generation to reach Available or
  explicitly say "submitted" and print how to inspect status. Adding
  `observedGeneration` is necessary for a reliable wait.

### CVC-10: transient API errors are treated as terminal

- Severity: P1 / High reliability
- File: Config reconciler
- Functions: `Reconcile`, `markError`
- Problem: almost every failure is written to Error status and returned as
  `(Result{}, nil)`. Temporary GET/CREATE/UPDATE/API availability failures do
  not receive controller-runtime rate-limited retries.
- Recommendation: classify invalid user/template data as terminal status, but
  return infrastructure/API errors so controller-runtime retries them.

### CVC-11: dependency loss leaves stale output and status

- Severity: P1 / Requires product decision
- File: Config reconciler
- Function: `markError`
- Problem: deleting the input Secret or template changes the Config to Error but
  retains the last materialized output and `status.secretRef`.
- Evidence: CFG-022 and CFG-026.
- Recommendation: decide and document last-known-good versus fail-closed
  semantics. Credential revocation generally argues for fail-closed or an
  explicit policy. At minimum, expose whether the referenced output is stale.

### CVC-12: broad watches trigger expensive scans

- Severity: P2 / Medium
- File: Config reconciler
- Functions: `findConfigsForTemplate`, `findConfigsForSecret`,
  `findConfigsForLegacyTemplateConfigMap`
- Problem: template and legacy-template events list every Config cluster-wide;
  Secret events list every Config in the namespace. The controller also watches
  all Secrets and ConfigMaps.
- Evidence: CFG-048 and source inspection.
- Recommendation: add field indexes for normalized template reference and
  properties Secret reference, then query by index. Add predicates for relevant
  ConfigMaps and meaningful generations.

### CVC-13: status and observability are incomplete

- Severity: P2 / Medium
- Files: Config API/status and both reconcilers
- Problem: no `observedGeneration`; Error retains an old `secretRef`; event
  recorders are constructed but no Kubernetes Events are emitted.
- Evidence: CFG-043/CFG-044.
- Recommendation: add observed generation, make stale output explicit, and emit
  deduplicated warning/normal events for materialization and failures.

### CVC-14: RBAC and tenancy need tighter boundaries

- Severity: P1 / Security design review
- Files: Helm RBAC templates and controller setup
- Problem: chart rules are broad (`*` verbs/resources in relevant paths), while
  cross-namespace template lookup and cluster-wide watches give the controller
  wide reach. Required permissions also depend on existing cluster-admin-style
  bindings when authentication is disabled.
- Recommendation: document the trust model, split exact Config/status,
  ConfigTemplate/status, Secret, and legacy ConfigMap permissions, and test with
  a restricted service account. Decide whether arbitrary cross-namespace
  template references are acceptable in multi-tenant clusters.

### Additional compatibility finding

When the CRDs are installed, template/config list and delete paths prefer CRDs
exclusively rather than merging CRD and legacy storage. That is inconsistent
with "dual-read, single-write" backward compatibility and can hide addon-shipped
legacy templates and configs. Template `scope` also changes from documented
`project/system` terminology to `namespace/system`; the CLI maps non-system
values to namespace. This may be intentional, but it requires migration and API
documentation.

## 3. Imperative and controller comparison

| Behavior | Imperative implementation | Controller implementation | Classification |
|---|---|---|---|
| Template storage | `config-template-*` ConfigMap | ConfigTemplate CR | Expected difference |
| Config storage | Rendered Secret is the source of record | Config CR is source; owned Secret is materialized | Expected difference |
| Template parsing/schema | Parsed during apply/load | Reconciled into status | Pass |
| Inline properties | Supported | Supported | Pass except sensitive templates |
| Secret-backed properties | Workflow/read paths vary | Native `propertiesFrom` | Pass |
| Sensitive input | CLI values do not enter a CR | Inline is accepted; CLI companion leaks | Bug |
| CUE defaults/strings/nested values | Supported | Supported | Pass |
| CUE integer | Supported | JSON integer becomes float and fails | Bug |
| Custom validation | Returns validation message | Error status/webhook denial when installed | Mostly same |
| Invalid CUE | Apply fails | Admitted, then Error | Bug against issue contract |
| Both property sources | Not applicable as a single old API field | Admitted, then Error | Bug against issue contract |
| Default Secret type | `/<template-name>` | `Opaque` | Bug |
| Forced labels/annotations | Applied | Applied | Pass |
| Input-properties annotation/data | Stored for read/list UX | Stored in output | Pass |
| Arbitrary `outputs` | Created and tracked in Secret references | Ignored by controller | Missing feature |
| Expanded writer/Nacos | Supported | Unsupported | Missing feature |
| Idempotent apply | Create-or-update | Stable reconciliation | Pass |
| Manual output drift/deletion | No continuous repair | Repaired | Expected improvement |
| Template update | Existing configs are not automatically rerendered | Dependents rerender | Expected improvement |
| Input Secret update | Command must run again | Dependents rerender | Expected improvement |
| Change template reference | Rejected by `ErrChangeTemplate` | Allowed | Undocumented difference |
| Output name change | Old lifecycle handled imperatively/tracked | Old owned Secret remains | Bug |
| Config deletion | Explicitly deletes tracked objects | Owner GC deletes owned Secrets | Pass for supported output |
| Missing dependency | Command returns an immediate error | Error status, then watch-based recovery | Expected declarative difference |
| Unowned name collision | Conflict/error | Refuses adoption/overwrite | Pass |
| Status | Synchronous CLI error/result | Asynchronous phase/conditions | Expected difference; incomplete status |
| Distribution | Existing Application-based mechanism | Still Secret-based; not redesigned | Out of scope, partially checked |
| Workflow create/delete | Imperative Secret lifecycle | Still imperative, not CRD-backed | Missing feature |
| Legacy coexistence | Native | Template fallback exists, list/delete coexistence broken | Bug |

## 4. E2E test results

The complete per-case table with actual result and classification is in
[RESULTS.md](RESULTS.md). In summary:

- Creation and steady-state reconciliation: CFG-001, 002, 004-017 passed.
- Failure recovery: CFG-018-020 and 026 recovered through dependency watches.
- Data and schema edge cases: CFG-030 found integer corruption; CFG-032 passed
  Unicode, quotes, and multiline content; CFG-033 passed custom validation.
- Lifecycle: CFG-024 found leaked old outputs; CFG-025 confirmed owner-GC on
  Config deletion.
- Security/admission: CFG-003, 034, 035, and 040 found blocking issues.
- Compatibility: CFG-037-041 found Secret-type, outputs, CLI, and workflow gaps.
- Controller quality: CFG-043, 044, and 048 found status, event, and scaling
  concerns.

For each live test, I inspected the relevant metadata, owner references, type,
data, status, UID, and resourceVersion. The fixtures remain in this directory.
The isolated namespace is also still available for inspection.

## 5. Failed tests

### CFG-030: explicit integer

1. Apply a template requiring `count: int`.
2. Imperative dry-run with `count=3` succeeds.
3. Create an equivalent Config CR with JSON/YAML integer `3`.
4. Actual: Config reaches Error and no output Secret is created.

Root cause: generic JSON unmarshalling converts the value to `float64` before
CUE evaluation.

### CFG-024: output rename

1. Create a Config whose template renders Secret `audit-renamed-one`.
2. Change the properties/template so the output name is
   `audit-renamed-two`.
3. Actual: both Secrets remain and both are owned by the Config.

Root cause: reconciliation applies only the newly desired name and loses the
prior name after overwriting `status.secretRef`.

### CFG-035: sensitive inline input

1. Create a sensitive ConfigTemplate.
2. Create a Config with inline properties.
3. Actual: the API stores the value and the controller reaches Available.

Root cause: sensitive is used for output metadata/read behavior but never as an
admission or reconciliation constraint.

### CFG-038/039: outputs fallback is unmanageable

1. Apply a template with `outputs`.
2. Run `vela config create`; it prints a fallback message and creates legacy
   resources.
3. Run list and delete with Config CRDs installed.
4. Actual: list omits the config; delete reports it does not exist.

Root cause: create is dual-path, while list/delete are CRD-only whenever API
discovery succeeds.

### CFG-040: companion Secret leak

1. Use CLI create with a sensitive template.
2. Observe `<name>-properties` with no owner reference.
3. Delete the Config.
4. Actual: output is collected, but the input credential Secret remains.

### CFG-041: workflow remains imperative

1. Run an Application containing the `create-config` workflow step.
2. Actual: workflow succeeds and a legacy config Secret is created, but no
   Config CR exists.

### CFG-003/034: webhook contract

The live API server admitted the objects because this IDE-run cluster had no
ValidatingWebhookConfiguration installed. Source and unit tests additionally
show that, even if installed, the handlers intentionally allow invalid
ConfigTemplate CUE and mutually exclusive Config fields. These are therefore
implementation issues, not just a limitation of the test environment.

## 6. Missing functionality

- Controller materialization of `template.outputs` and tracking/deletion of
  those arbitrary resources.
- Expanded-writer/Nacos execution through the controller.
- Workflow `create-config` creation of Config CRs.
- Safe CRD/legacy coexistence for list, show, and delete operations.
- Full admission contract from the issue: invalid CUE, mutual exclusivity, and
  sensitive inline rejection.
- Exact output normalization parity, including default Secret type.
- A defined cleanup policy when rendered resource identity changes.

## 7. Documentation gaps

Document before release:

- ConfigTemplate and Config schemas with complete examples.
- `properties` versus `propertiesFrom`, Secret key default, and sensitive-data
  requirements.
- Template reference namespace defaulting and whether cross-namespace
  references are part of the supported tenancy model.
- `namespace/system` scope terminology and migration from `project/system`.
- Asynchronous status phases, conditions, reconciliation latency, and recovery.
- Last-known-good versus fail-closed behavior after template/input deletion.
- Update semantics, including template mutation and output-name changes.
- Ownership and deletion behavior for output and companion Secrets.
- Unsupported `outputs`/expanded writers and how legacy fallback is managed.
- CLI wording and how users determine whether submission ultimately succeeded.
- Migration/coexistence behavior for existing legacy templates/configs.

When neither the issue nor the code establishes a policy, this report uses
`UNCLEAR / REQUIRES DECISION` instead of calling the behavior a bug.

## 8. Test coverage gaps

### Unit tests

- `TestResolvePropertiesPreservesIntegers`: JSON integer remains a CUE integer.
- `TestSensitiveInlinePropertiesRejected`: webhook and reconciler defense.
- `TestOutputNormalizationMatchesFactory`: exact labels, annotations, namespace,
  input properties, and Secret type.
- `TestRenderedNameChangeRetiresOldOwnedSecret`: safe old-output cleanup.
- `TestTransientAPIErrorsAreRetried`: distinguish API failures from user errors.

### Controller/envtest tests

- Admission denial for invalid CUE and both property sources.
- Sensitive inline denial and recovery with `propertiesFrom`.
- Missing Secret key repair, not only missing Secret repair.
- Template/input deletion policy and stale status assertions.
- Rapid updates and resourceVersion conflict injection.
- Delete/recreate with different owner UID.
- Field-indexed fan-out for many Configs.
- Manager startup with pre-existing Config objects.

### Integration/CLI tests

- CRD create waits/reports asynchronous failure correctly.
- Dual-read/list/delete with both CRD and legacy objects.
- Sensitive companion ownership, partial-failure cleanup, and collision safety.
- Exact imperative/controller object comparison for representative templates.
- ConfigTemplate metadata preservation; the current parse path also drops the
  template description, an older defect exposed during this audit.

### E2E tests

- Installed validating webhooks with `failurePolicy: Fail`.
- Controller restart and recovery from objects changed while stopped.
- Restricted service-account/RBAC operation.
- `outputs` lifecycle after controller support is implemented.
- Workflow create/read/delete on the CRD-backed lifecycle.
- Larger fan-out, rapid updates, and controller event/metrics checks.

Existing branch tests cover seven core reconciler cases: valid/invalid template,
inline input, Secret input, mutually exclusive input, Config deletion, and
legacy fallback. They do not cover the blocking parity and lifecycle cases
above.

## 9. Recommended changes

### P0: blocking

1. Enforce sensitive templates through `propertiesFrom`; fix and own/clean the
   CLI companion Secret.
2. Complete the issue's workflow migration to Config CRs.
3. Resolve `outputs`/expanded-writer support and make mixed CRD/legacy CLI
   operations consistently manageable.

### P1: important

1. Implement the promised webhook validation and install/test it with fail-safe
   behavior.
2. Preserve integers and share one property decoding/rendering implementation.
3. Clean up renamed old outputs safely.
4. Match imperative Secret normalization, especially the default type.
5. Stop reporting unconditional CLI success before status is observed.
6. Retry transient Kubernetes API failures.
7. Decide stale-output behavior and review cross-namespace/RBAC security.

### P2: improvements

1. Add `observedGeneration` and meaningful Kubernetes Events.
2. Replace full Config scans with field indexes and predicates.
3. Preserve ConfigTemplate description metadata.
4. Clarify template-reference mutation or enforce immutability.

### P3: documentation and tests

1. Publish the lifecycle, migration, namespace, security, status, and limitation
   documentation listed above.
2. Add the unit, envtest, integration, and E2E suites listed above.
