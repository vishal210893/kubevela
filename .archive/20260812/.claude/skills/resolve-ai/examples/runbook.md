# Runbook: order-processor High Error Rate

## Alert Metadata

| Field | Value |
|-------|-------|
| Monitor | [order-processor Error Rate > 1%](https://app.datadoghq.com/monitors/12345) |
| Severity | P2 (auto-escalates to P1 if > 5% for 10 min) |
| Service | order-processor |
| Team | pod-commerce |

## When This Fires

The 5xx error rate for order-processor has exceeded 1% of total requests over a 5-minute rolling window. This means at least 1 in 100 order processing attempts is failing. At current traffic (~500 orders/min), this represents ~5+ failed orders per minute.

## Immediate Assessment (< 2 min)

**1. Confirm current error rate:**
```
sum:trace.grpc.request.errors{service:order-processor,env:production}.as_rate() / sum:trace.grpc.request.hits{service:order-processor,env:production}.as_rate() * 100
```

**2. Check if a deployment just happened:**
```
events("sources:kubernetes tags:kube_deployment:order-processor").rollup("count").last("15m")
```

**3. Check downstream dependency health:**
```
sum:trace.grpc.request.errors{service:payment-gateway,env:production}.as_rate()
sum:trace.grpc.request.errors{service:inventory-service,env:production}.as_rate()
avg:kafka.consumer.lag{consumer_group:order-processor,env:production}
```

**4. Quick impact check:**
- Is error rate increasing, stable, or decreasing?
- Are errors concentrated on a single endpoint or spread across all?
- Is revenue being impacted (check order success rate)?

## Troubleshooting Steps

### Step 1: Identify error pattern

**Check:**
```
service:order-processor env:production status:error | group by @error.kind
```

**Look for:** A dominant error type (e.g., `connection_refused`, `timeout`, `internal_error`, `unavailable`)

**If `connection_refused` or `unavailable`:** Likely downstream dependency failure — jump to Step 3.
**If `timeout`:** Jump to Step 2 to check resource utilization.
**If `internal_error`:** Check recent deployments — possible code bug.
**If not clear:** Continue to Step 2.

### Step 2: Check resource utilization

**Check:**
```
avg:kubernetes.cpu.usage.total{kube_deployment:order-processor,kube_namespace:commerce}
avg:kubernetes.memory.usage{kube_deployment:order-processor,kube_namespace:commerce}
avg:kubernetes.memory.limits{kube_deployment:order-processor,kube_namespace:commerce}
```

**Look for:** CPU > 80% sustained, memory approaching limits, OOMKilled events

**If OOM detected:**
```
events("sources:kubernetes tags:kube_deployment:order-processor reason:OOMKilled").rollup("count").last("1h")
```
Restart pods and scale up immediately.

**If resources normal:** Continue to Step 3.

### Step 3: Check downstream dependencies

**Check database connections:**
```
avg:postgresql.connections.active{service:order-processor-db}
avg:postgresql.connections.max{service:order-processor-db}
```

**Check Kafka consumer lag:**
```
avg:kafka.consumer.lag{consumer_group:order-processor,env:production}
```

**Check payment-gateway latency:**
```
avg:trace.grpc.request.duration{service:payment-gateway,env:production}
```

**Look for:** Connection pool exhaustion (active near max), consumer lag spiking, downstream latency increase

**If DB connections exhausted:** Kill long-running queries, consider scaling connection pool.
**If Kafka lag spiking:** Check for poison messages, scale consumer group.
**If payment-gateway slow:** Check payment-gateway runbook, consider enabling circuit breaker.
**If all normal:** Escalate — unknown root cause.

## Common Root Causes

| Cause | Symptoms | Resolution | Time to Fix |
|-------|----------|------------|-------------|
| Bad deployment | Errors start exactly at deploy time | `argocd app rollback order-processor` | 5 min |
| DB connection exhaustion | `connection_refused` errors, active connections at max | Kill long queries, restart pods | 5 min |
| Kafka consumer lag | Processing delays, message backlog growing | Scale consumers, check for poison messages in DLQ | 10 min |
| OOM kills | Pods restarting, memory at limit before restart | Restart pods, scale replicas or increase memory limit | 2 min |
| Payment gateway timeout | `timeout` errors on payment calls only | Check payment-gateway service, enable circuit breaker | Varies |
| Inventory service degradation | Errors only on inventory check calls | Check inventory-service, orders queue up | Varies |
| Redis connection failure | Idempotency check failures, cache misses spike | Check ElastiCache health, restart if needed | 5 min |

## Mitigation Actions

**Rollback last deployment:**
```bash
argocd app rollback order-processor
# Or via kubectl:
kubectl rollout undo deployment/order-processor -n commerce
```

**Restart pods (rolling):**
```bash
kubectl rollout restart deployment/order-processor -n commerce
```

**Scale up:**
```bash
kubectl scale deployment/order-processor -n commerce --replicas=8
# Normal is 4 replicas — scale to 8 during incidents
```

**Kill long-running DB queries:**
```sql
-- Find queries running > 60 seconds
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle' AND now() - pg_stat_activity.query_start > interval '60 seconds';

-- Terminate specific query
SELECT pg_terminate_backend(<pid>);
```

**Check and clear Kafka DLQ:**
```bash
# Check DLQ message count
kubectl exec -it deploy/order-processor -n commerce -- /app/cli dlq-status
# Reprocess DLQ messages (after root cause resolved)
kubectl exec -it deploy/order-processor -n commerce -- /app/cli dlq-reprocess
```

## Escalation

| Condition | Action | Contact |
|-----------|--------|---------|
| Error rate > 5% for 10 min | Page SRE lead | @sre-lead (PagerDuty) |
| Error rate > 1% for 30 min | Escalate to pod lead | @commerce-lead (Slack) |
| Revenue impact suspected | Notify business stakeholders | #commerce-leadership (Slack) |
| Root cause unknown after 30 min | Engage platform team | #platform-incidents (Slack) |

**When escalating, include:**
- Alert link and current error rate values
- What troubleshooting steps you've completed
- Timeline: when did errors start, any correlation with deploys/changes
- Current mitigation status (did rollback/restart help?)
- Affected order volume estimate
