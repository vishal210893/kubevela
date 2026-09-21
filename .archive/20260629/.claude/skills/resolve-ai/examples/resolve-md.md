# order-processor — Resolve.ai Knowledge

## System Overview

| Field | Value |
|-------|-------|
| Service ID | AID-order-processor |
| Type | Microservice |
| Product Family | commerce |
| Exposure | internal |
| Language | Go |
| Description | Processes e-commerce orders: validates inventory, charges payment via payment-gateway, dispatches fulfillment events to Kafka |

## Ownership

| Role | Contact |
|------|---------|
| Pod Owner | pod-commerce |
| Emergency Contact | pod-commerce@company.com |
| Slack Channel | #commerce-incidents |
| On-Call Rotation | pod-commerce-oncall (PagerDuty) |
| Business Risk | High |
| Security Risk | Medium |

## Architecture

### Dependencies

| Direction | Service | Protocol | Purpose |
|-----------|---------|----------|---------|
| Upstream | api-gateway | gRPC | Receives order creation requests |
| Upstream | order-queue (Kafka) | Consumer | Processes async order events |
| Downstream | payment-gateway | gRPC | Charges customer payment |
| Downstream | inventory-service | gRPC | Reserves and validates inventory |
| Downstream | notification-service | Kafka | Sends order confirmation emails |
| Downstream | fulfillment-service | Kafka | Dispatches fulfillment events |

### Infrastructure

| Component | Details |
|-----------|---------|
| Cloud Provider | AWS (EKS, RDS, ElastiCache) |
| K8s Namespaces | commerce |
| Environments | staging, production |
| Deployment | Helm chart via ArgoCD |

### Datastores

| Store | Type | Purpose |
|-------|------|---------|
| order-db (RDS PostgreSQL) | Primary DB | Order state, transaction history |
| order-cache (ElastiCache Redis) | Cache | Idempotency keys, rate limiting |
| order-events (Kafka) | Event bus | Order lifecycle events |

### Architecture Summary

order-processor is the central orchestrator for the order lifecycle. It consumes order requests from either the gRPC API or the order-queue Kafka topic, validates inventory availability, initiates payment capture, and publishes fulfillment events. All state is stored in PostgreSQL with Redis used for idempotency and caching. The service is stateless and horizontally scalable.

## Glossary

| Term | Definition |
|------|-----------|
| OPS | Order Processing Service (this service) |
| DLQ | Dead Letter Queue — failed Kafka messages that exceeded retry limits |
| Fulfillment event | Kafka message triggering warehouse pick/pack/ship |
| Inventory reservation | Temporary hold on stock during payment processing (5 min TTL) |
| Idempotency key | Redis-cached key preventing duplicate order processing |
| Payment capture | Actual charge to customer (vs. authorization) |

## Investigation Best Practices

### Logs

```
service:order-processor env:production
```

Error logs with grouping:
```
service:order-processor env:production status:error | group by @error.kind
```

Payment-related errors:
```
service:order-processor env:production @message:*payment* status:error
```

### Metrics

Request duration and error rates:
```
avg:order_processor.request.duration{service:order-processor,env:production}
sum:trace.grpc.request.errors{service:order-processor,env:production}.as_rate()
```

Order processing throughput:
```
sum:order_processor.orders.processed{env:production}.as_count()
sum:order_processor.orders.failed{env:production}.as_count()
```

Resource utilization:
```
avg:kubernetes.cpu.usage.total{kube_deployment:order-processor,kube_namespace:commerce}
avg:kubernetes.memory.usage{kube_deployment:order-processor,kube_namespace:commerce}
```

### Traces

```
service:order-processor env:production resource_name:ProcessOrder
```

Slow traces (> 500ms):
```
service:order-processor env:production @duration:>500000000
```

### Key Dashboards

| Dashboard | Purpose | Link |
|-----------|---------|------|
| Order Processing Overview | Throughput, latency, error rates | [Datadog](#) |
| Commerce SLOs | SLO burn rates and budgets | [Datadog](#) |
| Payment Gateway Health | Payment success rates, latency | [Datadog](#) |
| Kafka Consumer Lag | Consumer group lag for order-processor | [Datadog](#) |

## SLOs

| SLO | Target | Metric | Dashboard |
|-----|--------|--------|-----------|
| Availability | 99.9% | `1 - (sum:trace.grpc.request.errors / sum:trace.grpc.request.hits)` | Commerce SLOs |
| Latency P99 | < 500ms | `p99:order_processor.request.duration{env:production}` | Commerce SLOs |
| Order Success Rate | 99.5% | `1 - (sum:order_processor.orders.failed / sum:order_processor.orders.processed)` | Commerce SLOs |

## Slash Commands

| Command | Description |
|---------|-------------|
| `kubectl rollout restart deployment/order-processor -n commerce` | Restart all pods |
| `kubectl scale deployment/order-processor -n commerce --replicas=N` | Scale to N replicas |
| `argocd app rollback order-processor` | Rollback to previous deployment |
| `kubectl exec -it deploy/order-processor -n commerce -- /app/healthcheck` | Run health check |
| `kubectl logs -l app=order-processor -n commerce --tail=100` | Tail recent logs |

## Escalation

| Severity | Action | Who | Timeline |
|----------|--------|-----|----------|
| P1 — Orders failing | Page on-call immediately | pod-commerce-oncall (PagerDuty) | Immediate |
| P2 — Degraded latency/errors | Slack #commerce-incidents | pod-commerce on-call | 15 min |
| P3 — Minor errors, no user impact | Jira ticket in COMMERCE board | pod-commerce | 24 hr |
| P4 — Tech debt/improvement | Backlog grooming | pod-commerce | Sprint |
