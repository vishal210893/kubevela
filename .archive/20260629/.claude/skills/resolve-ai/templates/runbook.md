# Runbook: {{ALERT_NAME}}

## Alert Metadata

| Field | Value |
|-------|-------|
| Monitor | {{MONITOR_LINK}} |
| Severity | {{SEVERITY}} |
| Service | {{SERVICE_NAME}} |
| Team | {{TEAM}} |

## When This Fires

{{TRIGGER_DESCRIPTION}}

## Immediate Assessment (< 2 min)

Run these checks to understand the scope:

**1. Confirm the alert is real:**
```
{{CONFIRMATION_QUERY}}
```

**2. Check impact scope:**
```
{{IMPACT_QUERY}}
```

**3. Answer these questions:**
- Is it affecting end users?
- Is the error rate increasing or stable?
- Did a deployment just happen?
- Are other services also affected?

**4. Check for recent deployments:**
```
events("sources:kubernetes tags:service:{{SERVICE_NAME}}").rollup("count").last("15m")
```

## Troubleshooting Steps

### Step 1: {{STEP_1_TITLE}}

**Check:**
```
{{STEP_1_QUERY}}
```

**Look for:** {{STEP_1_LOOK_FOR}}

**If found:** {{STEP_1_ACTION_IF_FOUND}}
**If not:** Continue to Step 2.

### Step 2: {{STEP_2_TITLE}}

**Check:**
```
{{STEP_2_QUERY}}
```

**Look for:** {{STEP_2_LOOK_FOR}}

**If found:** {{STEP_2_ACTION_IF_FOUND}}
**If not:** Continue to Step 3.

### Step 3: {{STEP_3_TITLE}}

**Check:**
```
{{STEP_3_QUERY}}
```

**Look for:** {{STEP_3_LOOK_FOR}}

**If found:** {{STEP_3_ACTION_IF_FOUND}}
**If not:** Escalate per the escalation section below.

## Common Root Causes

| Cause | Symptoms | Resolution | Time to Fix |
|-------|----------|------------|-------------|
{{ROOT_CAUSE_ROWS}}

## Mitigation Actions

### Immediate Mitigations

**Rollback last deployment:**
```
{{ROLLBACK_COMMAND}}
```

**Restart pods:**
```
{{RESTART_COMMAND}}
```

**Scale up:**
```
{{SCALE_COMMAND}}
```

{{ADDITIONAL_MITIGATIONS}}

## Escalation

| Condition | Action | Contact |
|-----------|--------|---------|
{{ESCALATION_ROWS}}

**When escalating, include:**
- Alert link and current values
- What you've checked so far
- Timeline of when the issue started
- Any recent changes (deploys, config, infra)
