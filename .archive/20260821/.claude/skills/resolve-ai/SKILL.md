---
name: resolve-setup
description: Generate Resolve.ai team knowledge documents (RESOLVE.md, runbooks, docs) for any repository
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Resolve.ai Setup

Generate production-ready Resolve.ai knowledge documents for any repository by combining automated repo scanning with targeted human input.

## Quick Start

1. **Discover** — Run `discover.sh` to scan the repo and produce a JSON profile
2. **Analyze code** — Read source files to auto-discover dependencies and observability data
3. **Detect re-run** — If RESOLVE.md already exists, ask whether to update or start fresh
4. **Interview** — Ask only the questions that code analysis couldn't answer + conditional questions based on gaps
5. **Generate** — Fill templates using discovery data + code analysis + interview answers, present each for review
6. **Write** — Write approved files to `.resolve/` directory in the repo

## On-Demand Resources

Load these only when needed during generation:

| Resource | Path | Purpose |
|----------|------|---------|
| RESOLVE.md template | `templates/resolve-md.md` | Template with `{{PLACEHOLDER}}` syntax |
| Runbook template | `templates/runbook.md` | Per-alert runbook template |
| Doc template | `templates/doc.md` | Per-failure-scenario doc template |
| RESOLVE.md example | `examples/resolve-md.md` | Fully populated example (~120 lines) |
| Runbook example | `examples/runbook.md` | Fully populated runbook example |

## Phase 1: Discovery

Run the discovery script from the skill's scripts directory:

```bash
bash "SKILL_DIR/scripts/discover.sh"
```

Where `SKILL_DIR` is the absolute path to this skill's directory (resolve the path from SKILL.md location).

The script outputs JSON to stdout and status messages to stderr. Parse the JSON output. Key fields:

- `service_name`, `service_id`, `description` — from software-catalog.yaml
- `pod_owner`, `emergency_contact` — ownership info
- `language`, `languages` — detected tech stack
- `services` — Dockerfiles and docker-compose services found
- `k8s` — Kubernetes config (namespaces, environments, helm, kustomize)
- `datadog_monitors` — monitor definitions found
- `infra_provider` — cloud provider (aws, gcp, azure, or unknown)
- `datastores` — databases, caches, queues detected
- `has_existing_resolve_md` — re-run detection
- `has_slo` — SLO config detected
- `software_catalog_found` — whether software-catalog.yaml exists
- `gaps` — array of what was NOT found (drives interview questions)

## Phase 1.5: Code Analysis

After `discover.sh` completes, analyze the source code to auto-discover information that would otherwise require interview questions. Use the `language` field from Phase 1 to guide which patterns to look for.

### Dependencies (targets Q1)

**Goal:** Build a dependency table with direction, service name, protocol, and purpose.

**Search strategy — run these in parallel where possible:**

1. **Proto/gRPC definitions:** Glob for `**/*.proto` files. Read them to extract `service` definitions (this service exposes) and `import` paths (services it calls). Each `rpc` method reveals the purpose.

2. **HTTP/gRPC client usage by language:**
   - Go: Grep for `http.NewRequest`, `http.Get`, `http.Post`, `grpc.Dial`, `grpc.NewClient`, `sarama`, `confluent-kafka-go`, `segmentio/kafka-go`
   - Java: Grep for `@FeignClient`, `RestTemplate`, `WebClient`, `@GrpcClient`, `@KafkaListener`, `KafkaTemplate`, `@RabbitListener`
   - Node: Grep for `axios`, `node-fetch`, `got(`, `@grpc/grpc-js`, `kafkajs`, `amqplib`
   - Python: Grep for `requests.get`, `requests.post`, `httpx`, `grpc.insecure_channel`, `KafkaProducer`, `KafkaConsumer`, `pika`

3. **Service URLs in configuration:** Grep across env files (`.env.example`, `.env.sample`), config files (`application.yml`, `application.properties`, `config/*.yaml`), and K8s manifests for patterns like `*_SERVICE_URL`, `*_HOST`, `*_ENDPOINT`, `*_BASE_URL`, `*_GRPC_ADDR`.

4. **Docker-compose links:** If docker-compose files exist, check `depends_on` and `links` sections for service dependencies.

5. **Architecture docs:** If `ARCHITECTURE.md` or `README.md` exists, read for architecture descriptions, dependency lists, or system diagrams.

**For each dependency found, record:**

| Field | How to determine |
|-------|-----------------|
| Direction | `upstream` if something calls *this* service; `downstream` if *this* service calls it |
| Service | The service name (from URL, proto package, Feign client name, etc.) |
| Protocol | `gRPC`, `HTTP`, `Kafka`, `RabbitMQ`, `SQS`, etc. |
| Purpose | Inferred from method names, endpoint paths, or variable names |

### Observability (targets Q3)

**Goal:** Identify investigation starting points — dashboards, log queries, metric prefixes, health checks.

**Search strategy:**

1. **Dashboard URLs:** Grep for `app.datadoghq.com/dashboard`, `grafana.*/d/`, or any monitoring dashboard URLs in all files.

2. **Metric definitions:** Grep for metric client initialization and custom metric names:
   - Go: `statsd.New`, `datadog.New`, `prometheus.NewCounter`, `prometheus.NewHistogram`
   - Java: `@Timed`, `@Counted`, `MeterRegistry`, `StatsDClient`
   - Node: `hot-shots`, `prom-client`, `StatsD`
   - Python: `datadog.statsd`, `prometheus_client`
   - Terraform: Look in Datadog monitor files already discovered for `query` fields to extract metric prefixes

3. **Logging configuration:** Look for logging framework config:
   - `logback.xml`, `log4j2.xml` (Java)
   - Structured logging setup with service name tags
   - Datadog log configuration (`dd-trace`, `dd-java-agent`, `ddtrace`)

4. **Health check endpoints:** Grep for `/health`, `/ready`, `/readyz`, `/healthz`, `/status`, `/ping` in route definitions.

5. **Observability config files:** Check for `datadog.yaml`, `opentelemetry-collector-config.yaml`, `prometheus.yml`, or `otel-config.*` files.

### Code Analysis Results

Store the analysis results internally as two structures:

**`code_dependencies`** — list of `{direction, service, protocol, purpose}` entries

**`code_observability`** — object with:
- `dashboard_urls` — list of `{name, url}`
- `metric_prefix` — the primary metric prefix for this service (e.g., `order_processor`, `trace.http`)
- `health_endpoints` — list of health/readiness paths found
- `log_config` — logging framework and service tag if found

### Skip Conditions

**Q1 (Architecture & Dependencies) — SKIP if:**
- `code_dependencies` has ≥ 2 entries with identifiable protocols, AND
- Both `upstream` and `downstream` directions are represented

**Q3 (Investigation Starting Points) — SKIP if:**
- `code_observability.dashboard_urls` has ≥ 1 entry, OR
- `code_observability.metric_prefix` is identified AND the service name + K8s namespace from Phase 1 are available (sufficient to construct log/metric queries)

If a question is skipped, its auto-discovered data is used directly during generation (Phase 3). If only partial data was found (not enough to skip), present what was found and ask a **narrowed** version of the question targeting only the gaps.

### Present Combined Summary

After Phase 1 and Phase 1.5 complete, present a single summary to the user:

1. Service identity (name, language, type, owner) — from `discover.sh`
2. **Auto-discovered dependencies** — show the dependency table built from code analysis
3. **Auto-discovered observability** — show dashboards, metric prefix, health endpoints found
4. Infrastructure, datastores, monitors — from `discover.sh`
5. Gaps detected — from `discover.sh`
6. **Questions that will be asked** — list which questions still need answers and why
7. **Questions that were auto-answered** — list which questions were skipped, with a note: *"Correct these if anything is wrong or missing."*

Wait for the user to confirm or correct before proceeding to the interview.

## Re-run Detection

If `has_existing_resolve_md` is `true`:

1. Read the existing `RESOLVE.md` (or `.resolve/RESOLVE.md`)
2. Ask the user: **"RESOLVE.md already exists. Would you like to: (a) Update it with new findings, or (b) Start fresh?"**
3. If updating: use existing content as baseline, merge new discovery data
4. If fresh: proceed normally, old file will be replaced

## Phase 2: Interview

### Always-Asked Question

**Q2: Common Failure Modes**
> "What are the top 2-3 failure scenarios the on-call team encounters? For each, what's the typical root cause and first response?"

Q2 is always asked — failure modes require operational experience that cannot be inferred from code.

### Auto-Discoverable Questions (ask only if code analysis gaps remain)

**Q1: Architecture & Dependencies**

- **If skipped** (code analysis found ≥ 2 dependencies with protocols, covering both upstream and downstream): Use auto-discovered data. The user was shown findings in the combined summary and had a chance to correct.
- **If partial** (some dependencies found but skip condition not met): Show what was found and ask: *"I found these dependencies from the code: [table]. Are there additional upstream or downstream services I'm missing?"*
- **If no data**: Ask the full original question: *"What are the key upstream and downstream dependencies for {{SERVICE_NAME}}? (services it calls, services that call it, and the protocols used — e.g., gRPC, HTTP, Kafka)"*

**Q3: Investigation Starting Points**

- **If skipped** (dashboard URLs or metric prefix + service name found): Use auto-discovered data. The user was shown findings in the combined summary and had a chance to correct.
- **If partial** (e.g., metric prefix found but no dashboards): Show what was found and ask: *"I found metric prefix `[prefix]` and health endpoint `[path]` from the code. Are there specific Datadog dashboards or log queries the on-call team uses?"*
- **If no data**: Ask the full original question: *"When something goes wrong with {{SERVICE_NAME}}, what's the first thing you check? (specific Datadog dashboards, log queries, metrics, or commands)"*

### Conditional Questions (ask only if gap detected)

| Gap | Question |
|-----|----------|
| `no_software_catalog` | "What team owns this service? What's the Slack channel and on-call rotation?" |
| `no_k8s_manifests` | "How is this service deployed? (K8s namespace, environments, deployment tool)" |
| `no_datadog_monitors` | "What alerts exist for this service? (monitor names, thresholds, severity)" |
| `no_slo_config` | "What SLOs does this service have? (availability target, latency P99 target, other)" |
| `no_datastores_detected` | "What datastores does this service use? (databases, caches, queues, object stores)" |
| `no_infrastructure` | "What cloud provider and infrastructure does this service run on?" |
| `unknown_language` | "What language/framework is this service written in?" |

Ask all applicable questions (Q1/Q3 if needed + conditional) in a single batch to minimize back-and-forth.

## Phase 3: Generation & Review

### Step 1: Generate RESOLVE.md

1. Read the template: `templates/resolve-md.md`
2. Read the example: `examples/resolve-md.md`
3. Fill all `{{PLACEHOLDER}}` values using discovery JSON + code analysis results + interview answers
4. **Hard rule: output must be under 200 lines.** Be concise. Use tables, not paragraphs.
5. Include real Datadog query syntax (not placeholders) wherever possible
6. Present the complete RESOLVE.md to the user for review
7. Apply any requested changes
8. Write to `.resolve/RESOLVE.md`

### Step 2: Generate Runbooks

For each alert/monitor identified (from discovery `datadog_monitors` or interview Q2):

1. Read the template: `templates/runbook.md`
2. Read the example: `examples/runbook.md`
3. Fill all placeholders with service-specific details
4. Include actual Datadog queries using the service name and metric prefixes
5. Present each runbook for review
6. Write to `.resolve/runbooks/<alert-name>.md`

If no specific alerts were identified, generate at least one runbook for the most common failure mode described in the interview.

### Step 3: Generate Scenario Docs

For each failure scenario from interview Q2:

1. Read the template: `templates/doc.md`
2. Fill all placeholders, paying special attention to the **"Applies When"** field
3. The "Applies When" must be a clear, searchable description — Resolve uses this for retrieval
4. Include Datadog queries for investigation
5. Present each doc for review
6. Write to `.resolve/docs/<scenario-name>.md`

## Output Structure

```
.resolve/
├── RESOLVE.md                    # Primary knowledge document
├── runbooks/
│   ├── <alert-name-1>.md         # Per-alert runbook
│   └── <alert-name-2>.md
└── docs/
    ├── <scenario-name-1>.md      # Per-failure-mode document
    └── <scenario-name-2>.md
```

## Success Criteria

Before marking complete, verify:

- [ ] RESOLVE.md is under 200 lines
- [ ] RESOLVE.md has all sections from the template filled (no remaining `{{PLACEHOLDER}}` text)
- [ ] Every Datadog query uses real service names and metric prefixes (not placeholder text)
- [ ] Every runbook has concrete Datadog queries in the Immediate Assessment section
- [ ] Every runbook has a Common Root Causes table with at least 3 entries
- [ ] Every doc has a clear "Applies When" statement (not generic)
- [ ] Escalation matrix is complete with real team names and channels
- [ ] Glossary contains at least 3 service-specific terms
- [ ] All files are written to the `.resolve/` directory
- [ ] User has reviewed and approved each generated document
