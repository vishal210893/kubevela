# Addon-as-Component Differential Report

## Test Environment

| Field | Value |
|---|---|
| Date | `2026-07-09T16:13:05Z` |
| Cluster A | `addon-baseline` (baseline, `vela install`) |
| Cluster B | `addon-feature` (feature, local core) |
| Per-addon timeout | 300 seconds per cluster |

> **Documented asymmetry:** Cluster B uses `skipVersionValidate: true` because the out-of-cluster core cannot satisfy the `SystemRequirements` version check.
>
> **Fail-fast behavior:** This adapted harness fails immediately when enable/apply exits without creating the comparison Application, instead of waiting for the full timeout for a missing Application.

## Summary

| Outcome | Addons |
|---|---:|
| Total tested | 36 |
| Matching results | 30 |
| Both passed | 25 |
| Both failed | 5 |
| Discrepancies | 6 |

## Per-Addon Results

| Addon Name | Vela Install Result | Addon-as-Component Result | Match? | Notes / Error |
|---|---|---|---|---|
| `cert-manager` | PASS | PASS | MATCH (both pass) | |
| `chartmuseum` | PASS | PASS | MATCH (both pass) | |
| `cloudshell` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-cloudshell.txt` |
| `flink-kubernetes-operator` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-flink-kubernetes-operator.txt` |
| `grafana` | FAIL | FAIL | MATCH (both FAIL) | |
| `ingress-nginx` | PASS | PASS | MATCH (both pass) | |
| `keda` | PASS | PASS | MATCH (both pass) | |
| `kube-state-metrics` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-kube-state-metrics.txt` |
| `kube-trigger` | PASS | PASS | MATCH (both pass) | |
| `kubevela-io` | PASS | PASS | MATCH (both pass) | |
| `loki` | FAIL | FAIL | MATCH (both FAIL) | |
| `model-serving` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-model-serving.txt` |
| `model-training` | PASS | PASS | MATCH (both pass) | |
| `mysql-exporter` | PASS | PASS | MATCH (both pass) | |
| `netlify` | PASS | PASS | MATCH (both pass) | |
| `node-exporter` | PASS | PASS | MATCH (both pass) | |
| `o11y-definitions` | PASS | PASS | MATCH (both pass) | |
| `ocm-gateway-manager-addon` | FAIL | FAIL | MATCH (both FAIL) | |
| `ocm-hub-control-plane` | PASS | PASS | MATCH (both pass) | |
| `prometheus-server` | FAIL | FAIL | MATCH (both FAIL) | |
| `rollout` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-rollout.txt` |
| `terraform` | PASS | PASS | MATCH (both pass) | |
| `terraform-alibaba` | PASS | PASS | MATCH (both pass) | |
| `terraform-aws` | PASS | PASS | MATCH (both pass) | |
| `terraform-azure` | PASS | PASS | MATCH (both pass) | |
| `terraform-baidu` | PASS | PASS | MATCH (both pass) | |
| `terraform-ec` | PASS | PASS | MATCH (both pass) | |
| `terraform-gcp` | PASS | PASS | MATCH (both pass) | |
| `terraform-tencent` | PASS | PASS | MATCH (both pass) | |
| `terraform-ucloud` | PASS | PASS | MATCH (both pass) | |
| `traefik` | FAIL | FAIL | MATCH (both FAIL) | |
| `trivy-operator` | PASS | PASS | MATCH (both pass) | |
| `vegeta` | PASS | PASS | MATCH (both pass) | |
| `vela-core-shard-manager` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-vela-core-shard-manager.txt` |
| `vela-prism` | PASS | PASS | MATCH (both pass) | |
| `victoria-metric` | PASS | PASS | MATCH (both pass) | |

## Actionable Discrepancies

| Addon Name | Vela Install Result | Addon-as-Component Result | Match? | Notes / Error |
|---|---|---|---|---|
| `cloudshell` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-cloudshell.txt` |
| `flink-kubernetes-operator` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-flink-kubernetes-operator.txt` |
| `kube-state-metrics` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-kube-state-metrics.txt` |
| `model-serving` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-model-serving.txt` |
| `rollout` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-rollout.txt` |
| `vela-core-shard-manager` | TIMEOUT | FAIL | DISCREPANCY (A=TIMEOUT B=FAIL) | `diag/diag-*-addon-vela-core-shard-manager.txt` |
