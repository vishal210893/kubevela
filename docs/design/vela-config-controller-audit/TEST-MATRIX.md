# Vela Config controller verification matrix

> Test plan prepared before executing the controller audit.

Date: 2026-08-13

Test namespace: `cfg-audit-7105`

The matrix was derived from issue #7105, the imperative factory and CLI, the
new API types/controllers/webhooks, the chart, and the existing tests before
live test execution.

| ID | Scenario | Oracle / expected behavior | Evidence to inspect |
|---|---|---|---|
| CFG-001 | API discovery and CRD defaults | Both namespaced CRDs are served; template scope defaults to namespace | CRD schema, `kubectl explain` |
| CFG-002 | Valid ConfigTemplate | Available phase, success condition, usable schema | full CR YAML |
| CFG-003 | Invalid ConfigTemplate | Issue says admission denial; branch tests expect admitted Error phase | apply response, status |
| CFG-004 | Basic inline Config | Owned Secret with rendered data, metadata and Available status | Config and Secret YAML |
| CFG-005 | `propertiesFrom` Config | Same output as inline without properties in Config CR | input Secret, Config, output Secret |
| CFG-006 | Config without template | Freeform properties materialize using the legacy no-template convention | output Secret |
| CFG-007 | Legacy ConfigMap template fallback | Config renders from `config-template-*` ConfigMap | output and status |
| CFG-008 | CRD template precedence | CRD wins when CRD and legacy ConfigMap share a template name | output data |
| CFG-009 | Default template namespace | Empty `templateRef.namespace` resolves to `vela-system` | status and output |
| CFG-010 | ConfigTemplate reconcile stability | ResourceVersion becomes stable after convergence | repeated RV samples |
| CFG-011 | Config reconcile stability | Config and Secret RVs become stable after convergence | repeated RV samples |
| CFG-012 | Reapply identical Config | No duplicates or repeated side effects | UID, RV, object count |
| CFG-013 | Manual output deletion | Owned Secret is recreated | UID before/after |
| CFG-014 | Manual output drift | Desired data and metadata are restored | Secret YAML |
| CFG-015 | Config property update | Existing output updates and owner remains stable | UID, data, status |
| CFG-016 | Template update fan-out | Every referencing Config is rerendered | outputs and status |
| CFG-017 | Input Secret update fan-out | Referencing Config rerenders | output data |
| CFG-018 | Missing template recovery | Error becomes Available when template appears | conditions and output |
| CFG-019 | Invalid then fixed template | Template and dependent Config recover | phases and output |
| CFG-020 | Missing input Secret recovery | Error becomes Available when input appears | conditions and output |
| CFG-021 | Missing input key recovery | Error becomes Available when key is added | conditions and output |
| CFG-022 | Input Secret deletion | Config reports Error; stale-output policy is established | phase and existing output |
| CFG-023 | Change templateRef | Compare controller mutation with imperative `ErrChangeTemplate` | output and status |
| CFG-024 | Rendered Secret name changes | Old owned output must not remain orphaned | Secret inventory |
| CFG-025 | Delete Config | Owned materialized Secret is garbage-collected | NotFound checks |
| CFG-026 | Delete referenced template | Config behavior and output retention are explicit | phase and Secret inventory |
| CFG-027 | Delete and recreate Config | New UID owns a clean output | owner UID |
| CFG-028 | Cross-namespace template | Allowed only if intended; Config output remains in Config namespace | output namespace |
| CFG-029 | Properties reference namespace | Input Secret lookup is restricted to Config namespace | phase/error |
| CFG-030 | Required/default/scalar/nested parameters | CUE semantics match imperative renderer | output data |
| CFG-031 | Wrong and unknown parameter types | Issue says admission denial; controller must surface a useful failure | apply response/status |
| CFG-032 | Unicode, quotes and multiline values | Values round-trip without corruption | decoded Secret data |
| CFG-033 | `template.validation.$returns` | Same failure message semantics as imperative path | apply response/status |
| CFG-034 | Both property sources | Issue says admission denial; branch tests expect admitted Error phase | apply response/status |
| CFG-035 | Sensitive template with inline properties | Must be rejected because issue says sensitive input never enters CRD | stored CR YAML |
| CFG-036 | Pre-existing Secret collision | Controller refuses to adopt or overwrite unrelated Secret | phase and Secret UID/data |
| CFG-037 | Output Secret default type | Must match imperative synthesized `/<template-name>` type | Secret type |
| CFG-038 | `outputs` and expanded writer | Compare documented imperative support with controller behavior and CLI fallback | generated inventory/CLI output |
| CFG-039 | CLI apply/create/list/delete | New CLI uses CRDs and remains usable with legacy inputs as specified | command output and objects |
| CFG-040 | Sensitive CLI companion lifecycle | Input companion Secret ownership and cleanup are safe | ownerRefs and post-delete inventory |
| CFG-041 | Workflow create-config | Issue requires a Config CR; inspect actual storage and output | Config/Secret inventory |
| CFG-042 | Rapid updates | Final rendered state matches latest generation | generation, data |
| CFG-043 | Status completeness | Conditions, observed generation and user-facing messages are useful | status YAML |
| CFG-044 | Events and logging | Important transitions/failures are observable without event storms | events/logs |
| CFG-045 | Restart/existing objects | Existing resources converge after manager restart | reason from watches plus live restart if controllable |
| CFG-046 | Template with no output | Behavior matches documented optional output contract | output Secret |
| CFG-047 | Output is not a Secret | Rejected or reported consistently with issue and imperative behavior | response/status |
| CFG-048 | Many Configs share one template | Fan-out is correct and does not require cluster-wide full scans per event | outputs and code path |

## Result classifications

- PASS
- EXPECTED DIFFERENCE
- BUG
- MISSING FEATURE
- DOCUMENTATION GAP
- TEST GAP
- UNCLEAR / REQUIRES DECISION
