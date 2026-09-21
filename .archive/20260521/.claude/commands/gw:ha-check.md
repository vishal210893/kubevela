---
allowed-tools: Bash(python3:*), Bash(uv run:*), Bash(chmod:*), Bash(ls:*), Read, Grep, Glob
description: Java microservice HA analysis
model: sonnet
argument-hint: [directory]
---

## Context

- Scripts available: !`ls .claude/scripts/*.py 2>/dev/null || ls $WSROOT/.claude/scripts/*.py 2>/dev/null`
- Project structure: !`ls build.gradle pom.xml k8s/ build/k8s/ 2>/dev/null`

## Your task

Perform High Availability analysis on Java Spring Boot microservices:

1. **Determine scope**: Use $ARGUMENTS directory or current directory
2. **Check for Gradle**: If using generateKubeTemplates, note if build/k8s/ missing

3. **Run Spring Boot HA checks**:
```bash
uv run --no-project .claude/scripts/gw-ha-check.py [path]
```
Checks: @Retryable, @CircuitBreaker, backoff config, HikariCP settings, DNS TTL

4. **Run Kubernetes HA checks**:
```bash
.claude/scripts/gw-ha-check-k8s.py [path]
```
Checks: replicas, HPA, PDB, topology spread, anti-affinity, probes, resources

5. **Present results**:
   - Critical issues (must fix)
   - Warnings (should fix)
   - Recommendations with code examples
   - HA score summary

### What This Checks

**Java/Spring Boot**:
- Retry annotations and backoff strategy
- Circuit breakers (Resilience4j)
- HikariCP max-lifetime (30s for failover)
- DNS TTL configuration

**Kubernetes**:
- Minimum 2 replicas
- HorizontalPodAutoscaler
- PodDisruptionBudget
- Topology spread constraints
- Resource requests/limits
- Liveness/readiness probes

Execute immediately and present findings prioritized by severity.
