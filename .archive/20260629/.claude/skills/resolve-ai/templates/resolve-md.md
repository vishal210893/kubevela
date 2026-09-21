# {{SERVICE_NAME}} — Resolve.ai Knowledge

## System Overview

| Field | Value |
|-------|-------|
| Service ID | {{SERVICE_ID}} |
| Type | {{SERVICE_TYPE}} |
| Product Family | {{PRODUCT_FAMILY}} |
| Exposure | {{EXPOSURE}} |
| Language | {{LANGUAGE}} |
| Description | {{DESCRIPTION}} |

## Ownership

| Role | Contact |
|------|---------|
| Pod Owner | {{POD_OWNER}} |
| Emergency Contact | {{EMERGENCY_CONTACT}} |
| Slack Channel | {{SLACK_CHANNEL}} |
| On-Call Rotation | {{ONCALL_ROTATION}} |
| Business Risk | {{BUSINESS_RISK}} |
| Security Risk | {{SECURITY_RISK}} |

## Architecture

### Dependencies

| Direction | Service | Protocol | Purpose |
|-----------|---------|----------|---------|
{{DEPENDENCY_ROWS}}

### Infrastructure

| Component | Details |
|-----------|---------|
| Cloud Provider | {{INFRA_PROVIDER}} |
| K8s Namespaces | {{K8S_NAMESPACES}} |
| Environments | {{ENVIRONMENTS}} |
| Deployment | {{DEPLOYMENT_METHOD}} |

### Datastores

| Store | Type | Purpose |
|-------|------|---------|
{{DATASTORE_ROWS}}

### Architecture Summary

{{ARCHITECTURE_DESCRIPTION}}

## Glossary

| Term | Definition |
|------|-----------|
{{GLOSSARY_ROWS}}

## Investigation Best Practices

### Logs

```
service:{{SERVICE_NAME}} env:{{ENVIRONMENT}}
```

Filter by error level:
```
service:{{SERVICE_NAME}} env:{{ENVIRONMENT}} status:error
```

Filter by specific endpoint:
```
service:{{SERVICE_NAME}} env:{{ENVIRONMENT}} @http.url:{{ENDPOINT_PATTERN}}
```

### Metrics

Key request metrics:
```
avg:{{METRIC_PREFIX}}.request.duration{service:{{SERVICE_NAME}},env:{{ENVIRONMENT}}}
sum:{{METRIC_PREFIX}}.request.errors{service:{{SERVICE_NAME}},env:{{ENVIRONMENT}}}.as_rate()
```

Resource utilization:
```
avg:kubernetes.cpu.usage.total{kube_deployment:{{SERVICE_NAME}},kube_namespace:{{K8S_NAMESPACE}}}
avg:kubernetes.memory.usage{kube_deployment:{{SERVICE_NAME}},kube_namespace:{{K8S_NAMESPACE}}}
```

### Traces

```
service:{{SERVICE_NAME}} env:{{ENVIRONMENT}} resource_name:{{OPERATION_NAME}}
```

### Key Dashboards

| Dashboard | Purpose | Link |
|-----------|---------|------|
{{DASHBOARD_ROWS}}

## SLOs

| SLO | Target | Metric | Dashboard |
|-----|--------|--------|-----------|
{{SLO_ROWS}}

## Slash Commands

| Command | Description |
|---------|-------------|
{{SLASH_COMMAND_ROWS}}

## Escalation

| Severity | Action | Who | Timeline |
|----------|--------|-----|----------|
| P1 — Service Down | Page on-call immediately | {{P1_ONCALL}} | Immediate |
| P2 — Degraded | Slack alert + investigate | {{P2_CHANNEL}} | 15 min |
| P3 — Minor Issue | Create ticket, investigate next business day | {{P3_PROCESS}} | 24 hr |
| P4 — Improvement | Backlog item | {{P4_PROCESS}} | Sprint |
