# KubeVela `helmchart` Component — Lightning Talk

> Format: markdown slide outline (drop each `##` block into your slide tool).
> Audience: KubeVela OSS community (mixed end-users + contributors).
> Length: ~10 min, 6 content slides + title.
> Speaker notes are in the `Notes:` lines — they are not on the slide.

---

## Slide 0 — Title

# Native Helm in KubeVela
### The `helmchart` component — render Helm charts, no FluxCD

<your name> · <your handle> · KubeVela Community

Notes: One sentence to open — "Today, ~5 minutes on a component that lets you
deploy any Helm chart as a first-class KubeVela Application, without running
FluxCD." Set the expectation that there's a worked example at the end.

---

## Slide 1 — What is it

- A built-in KubeVela **component type**: `type: helmchart`
- Fetches a Helm chart, renders it, and deploys the result **as native OAM resources**
- Sources: **OCI registries**, **HTTPS Helm repos**, and **direct `.tgz` URLs**
- No FluxCD, no `HelmRelease` CRD — it's part of the Application model

Notes: The headline. A `helmchart` component is just another entry in
`spec.components`, alongside `webservice`, `worker`, etc. The chart's rendered
objects become outputs that KubeVela owns and tracks like anything else.

---

## Slide 2 — Why we needed it

**Before:** Helm in KubeVela meant the FluxCD addon.

- Extra controller to install, run, and upgrade
- Indirection: Application → `HelmRelease` → Flux → workload
- Drift between the OAM Application and Flux's own objects
- Weaker multi-cluster story (Flux runs per-cluster, outside OAM placement)

**The problem to solve:** make Helm a native, first-class citizen of the
Application — one controller, one resource graph, one ownership model.

Notes: This is the "why". Don't bash FluxCD — it's great software. The point
is that for KubeVela users, routing Helm through a second GitOps controller
added moving parts and broke the single-pane-of-glass model. Lead with the
pain the room has actually felt.

---

## Slide 3 — How it's defined

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: podinfo
spec:
  components:
    - name: podinfo
      type: helmchart            # <-- the component type
      properties:
        chart:
          source: podinfo                                    # chart name (repo) or oci:// or .tgz URL
          repoURL: https://stefanprodan.github.io/podinfo    # for repo charts
          version: "6.11.1"
        release:
          name: podinfo
          namespace: default
        values:                  # inline Helm values
          replicaCount: 3
        options:
          createNamespace: true
          skipTests: true
```

Notes: Walk the anatomy top-down: `chart` (where + which version),
`release` (name + target namespace), `values` (inline overrides),
`options` (Helm behavior flags — includeCRDs, wait, atomic, timeout, etc.).
Emphasize it reads like any other component — nothing Helm-specific leaks into
the Application contract.

---

## Slide 4 — How it works

```
Application (type: helmchart)
        │
        ▼
 CueX  helm provider  (pkg/cue/cuex/providers/helm)
        │
        ├─ 1. fetch chart      (OCI pull / repo index+download / .tgz GET)
        ├─ 2. resolve auth      (Secret → registry.Client / HTTPOption)
        ├─ 3. merge values      (inline  ▸  valuesFrom)
        ├─ 4. render templates  (Helm engine, CRDs ordered first)
        │
        ▼
 Rendered K8s objects  →  emitted as component outputs
        │
        ▼
 KubeVela applies + tracks them via ResourceTracker
 (multi-cluster placement, GC, status — same as any component)
```

Notes: The key mental model: the helm provider is a **renderer**, not a
deployer. It turns a chart into plain Kubernetes objects; KubeVela's normal
machinery does the applying, multi-cluster distribution, and garbage
collection. Chart bytes are cached with version-aware TTLs (immutable tags
cached longer, mutable tags refreshed often) so repeat reconciles are cheap.

---

## Slide 5 — Authentication & registries

**One `auth.secretRef` → a Kubernetes Secret. Supported types:**

| Secret type | Keys | Use for |
|---|---|---|
| `kubernetes.io/basic-auth` | `username`, `password` | OCI + HTTPS repos (most common) |
| `kubernetes.io/dockerconfigjson` | `.dockerconfigjson` | reuse `docker login` / `kubectl create secret docker-registry` |
| `Opaque` | `username`+`password` **or** `token` | bearer-token (Nexus/Artifactory), flexible setups |
| `kubernetes.io/tls` | `tls.crt`, `tls.key` (+ `ca.crt`) | mTLS client certs |

- Bearer tokens (RFC 6750) honored on **HTTPS** chart sources
- Verified against **Docker Hub** OCI; works for **GHCR, Quay, ECR, GAR, ACR, Harbor, Artifactory, Nexus**
- Cross-namespace rule: Secret must live in the **release** or **Application** namespace

```yaml
chart:
  source: oci://ghcr.io/my-org/charts/my-app
  version: "1.0.0"
  auth:
    secretRef:
      name: registry-creds      # a kubernetes.io/basic-auth Secret
```

Notes: This is the slide contributors will ask about. Mention the Docker Hub
host-alias quirk only if asked (registry-1.docker.io / index.docker.io /
docker.io all normalize to the canonical v1 credential key). Credentials are
re-validated on every reconcile — rotating the Secret changes the cache key
and forces a fresh authenticated pull.

---

## Slide 6 — Layered values (with a live result)

**Two sources, clear precedence:**

```yaml
values:                    # (3) inline — highest priority
  replicaCount: 5
valuesFrom:                # merged in order, later wins
  - kind: ConfigMap        # (1) base
    name: podinfo-base
  - kind: Secret           # (2) overrides
    name: podinfo-overrides
```

Precedence: **inline `values` ▸ later `valuesFrom` ▸ earlier `valuesFrom`**
(`valuesFrom` kinds: `ConfigMap`, `Secret`, `OCIRepository`; `key` defaults to `values.yaml`).

**Verified on a live cluster:**

| Field | ConfigMap | Secret | Inline | Deployed | Winner |
|---|---|---|---|---|---|
| `replicaCount` | 3 | — | **5** | **5** (5 pods) | inline |
| `cpu` limit | **100m** | — | — | **100m** | ConfigMap |
| `memory` limit | 256Mi | **512Mi** | — | **512Mi** | Secret |

Notes: Close on proof. This exact example is in `localtest/valuesfrom-layered.yaml`
with a `verify-...sh` script that asserts the merge. The story: non-conflicting
keys merge (cpu survives), conflicts resolve by precedence (memory→Secret,
replicas→inline). Then: "It's heading to GA — try it, file issues, the code is
in PR #7080 and the KEP is at design/vela-core/helm-component.md. Questions?"
