# Vela Config controller audit results

> Detailed execution ledger for the controller audit.

Date: 2026-08-13

Environment: `k3d-kubevela`, IDE-launched Vela Core from branch `issue-7105`

| ID | Actual result | Classification |
|---|---|---|
| CFG-001 | Both CRDs served and discoverable; scope defaulted to `namespace` | PASS |
| CFG-002 | Valid templates became Available with generated schema | PASS |
| CFG-003 | Invalid CUE was admitted and became Error; no webhook configuration was installed in this IDE setup | BUG against issue contract; environment limits live webhook call |
| CFG-004 | Basic/defaulted string and nested properties rendered an owned Secret with metadata | PASS |
| CFG-005 | `propertiesFrom` rendered and updated after input Secret changes | PASS |
| CFG-006 | No-template Config created a minimal owned Secret containing `input-properties` | PASS |
| CFG-007 | Legacy `config-template-*` fallback rendered and reacted to ConfigMap updates | PASS |
| CFG-008 | CRD template took precedence; deleting it returned to legacy ConfigMap | PASS |
| CFG-009 | Empty template namespace resolved to `vela-system`; output namespace forced to Config namespace | PASS |
| CFG-010 | ConfigTemplate resourceVersions stabilized after convergence | PASS |
| CFG-011 | Config resourceVersions stabilized after convergence | PASS |
| CFG-012 | Reapply reported unchanged; no duplicates | PASS |
| CFG-013 | Deleted owned Secret was recreated with a new UID | PASS |
| CFG-014 | Manual data and annotation drift were restored | PASS |
| CFG-015 | Config updates changed rendered output | PASS |
| CFG-016 | Template updates rerendered dependent Configs | PASS |
| CFG-017 | Input Secret updates rerendered dependent Configs | PASS |
| CFG-018 | Missing template recovered automatically after creation | PASS |
| CFG-019 | Invalid template and dependent Config recovered after CUE fix | PASS |
| CFG-020 | Missing input Secret recovered after creation | PASS |
| CFG-021 | Missing-key path covered statically/unit; live missing-object recovery passed | TEST GAP for live missing-key recovery |
| CFG-022 | Input deletion changed Config to Error but retained the old materialized Secret and status.secretRef | UNCLEAR / documentation gap; stale credential remains usable |
| CFG-023 | Controller allowed templateRef mutation; imperative factory rejects it with ErrChangeTemplate | EXPECTED DIFFERENCE not documented, or BUG if parity required |
| CFG-024 | Output rename left both old and new owned Secrets until Config deletion | BUG |
| CFG-025 | Deleting Config garbage-collected all its owned output Secrets | PASS |
| CFG-026 | Deleting template made dependents Error but retained output; recreation recovered | PASS with documentation gap for stale output |
| CFG-027 | Delete/recreate ownership behavior reasoned from owner UID and GC; partial live coverage | TEST GAP |
| CFG-028 | Cross-namespace template reference worked; output forced into Config namespace | PASS / documentation gap |
| CFG-029 | Source lookup is restricted to Config namespace by code | PASS / unit-covered |
| CFG-030 | Defaults, strings, nested, quotes, multiline and Unicode passed. Explicit JSON integers failed in controller but succeeded imperatively | BUG |
| CFG-031 | Invalid properties become Error when webhooks are absent; webhook unit tests deny schema mismatches | ENVIRONMENT LIMIT plus webhook deployment gap |
| CFG-032 | Unicode, quotes and multiline round-tripped in output payload | PASS |
| CFG-033 | Custom validation became Config Error with the template message | PASS for controller; live admission not installed |
| CFG-034 | Both sources were admitted and became Error; issue requires webhook rejection | BUG against issue contract |
| CFG-035 | Sensitive inline values were admitted, stored in Config spec, and materialized | SECURITY BUG |
| CFG-036 | Unowned Secret collision was rejected without overwrite | PASS |
| CFG-037 | Controller defaulted output type to Opaque; imperative dry-run emitted `/<template-name>` | BUG / parity regression |
| CFG-038 | Controller ignored `outputs`; CLI fell back to legacy Secret/ConfigMap storage | MISSING FEATURE with broken mixed-mode UX |
| CFG-039 | CLI used CRDs for basic cases, but reported success before reconcile; integer example ended Error. Legacy fallback config was invisible and undeletable | BUG |
| CFG-040 | CLI sensitive companion input Secret had no owner and remained after Config deletion | BUG / credential leak |
| CFG-041 | `create-config` workflow succeeded but created only a legacy Secret, not a Config CR | MISSING FEATURE against issue scope |
| CFG-042 | Rapid-update race not stress-tested live; final-state patterns reviewed statically | TEST GAP |
| CFG-043 | Conditions useful but no observedGeneration; Error retains stale secretRef | DESIGN / DOCUMENTATION GAP |
| CFG-044 | Config controllers emitted no Kubernetes Events despite constructing recorders | TEST/OBSERVABILITY GAP |
| CFG-045 | Startup list/watch semantics support existing objects; actual restart not performed because IDE process lifecycle is user-controlled | REASONED PASS / live gap |
| CFG-046 | No-output template created an empty Secret plus input-properties, matching imperative optional-output behavior except type | PASS with CFG-037 difference |
| CFG-047 | Non-Secret output became Error | PASS |
| CFG-048 | Fan-out works but performs cluster-wide Config list scans for every template/legacy-template event | PERFORMANCE CONCERN |

## Commands and suites

- Targeted API/factory/controller/webhook/CLI tests passed.
- Config-focused Ginkgo CLI suite passed.
- `git diff --check master..anishbista60/issue-7105` passed.
- Helm rendering showed config webhooks and broad config/Secret permissions.
- Current cluster contained CRDs but no `ValidatingWebhookConfiguration`, so admission
  was evaluated from source and unit tests, not through the API server.
