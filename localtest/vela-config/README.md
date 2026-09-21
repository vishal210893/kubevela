# Vela config and config-template walkthrough

Files in this directory demonstrate the KubeVela config subsystem end to end:
authoring a template, creating a config from it, and consuming the result from
an Application.

| File | Role |
| --- | --- |
| `template-image-registry.cue` | Config template. Renders a `kubernetes.io/dockerconfigjson` Secret. |
| `props-registry.yaml` | Property values fed to `vela config create -f`. |
| `config-template-image-registry.yaml` | CRD-native `ConfigTemplate` form of the image-registry template. |
| `config-image-registry.yaml` | CRD-native `Config` with inline example properties. |
| `app-consume-secret.yaml` | Application that references the rendered Secret via `imagePullSecrets`. |
| `app-config-workflow.yaml` | Application that creates and reads the config from its own workflow. |

The credentials in `props-registry.yaml` and `app-config-workflow.yaml` are
placeholders. Replace them before pointing this at a real registry.

## CRD-native example

This branch introduces `ConfigTemplate` and `Config` custom resources. Apply the
template first and wait for its controller to compile the CUE schema:

```bash
kubectl apply -f localtest/vela-config/config-template-image-registry.yaml
kubectl wait -n vela-system \
  --for=jsonpath='{.status.phase}'=Available \
  configtemplate/demo-image-registry \
  --timeout=60s
```

Then replace the placeholder credentials in `config-image-registry.yaml` and
create the config:

```bash
kubectl apply -f localtest/vela-config/config-image-registry.yaml
kubectl wait -n default \
  --for=jsonpath='{.status.phase}'=Available \
  config/demo-registry \
  --timeout=60s
kubectl get secret demo-registry -n default -o yaml
```

The `Config` controller renders the template into a Secret named
`demo-registry`, records it in `status.secretRef`, and makes the Config its
controller owner. Because this concise example uses inline properties, use only
placeholder values in source control; for real credentials, use
`spec.propertiesFrom.secretRef`.

## Prerequisites

A running k3d cluster with KubeVela installed:

```bash
export KUBECONFIG=~/.kube/master.yaml
kubectl get pods -n vela-system
```

## 1. Apply the template

```bash
vela config-template apply -f localtest/vela-config/template-image-registry.cue -n vela-system
```

Expected output:

```
the config template demo-image-registry applied successfully
```

The template is stored as a ConfigMap named `config-template-demo-image-registry`:

```bash
kubectl get cm -n vela-system config-template-demo-image-registry -o yaml
```

Its `data` holds four keys: `template` (the CUE source), `schema` (the OpenAPI
schema derived from the `parameter` block), `expanded-writer`, and the labels
`config.oam.dev/catalog: velacore-config` and `config.oam.dev/scope: namespace`.

## 2. List and inspect the template

```bash
vela config-template list -n vela-system
vela config-template show demo-image-registry -n vela-system
```

`show` prints the generated property documentation: `registry` (default
`index.docker.io`), `username`, and `password`, all required strings.

## 3. Render the config without writing it

```bash
vela config create demo-registry \
  -t vela-system/demo-image-registry \
  -f localtest/vela-config/props-registry.yaml \
  -n default \
  --dry-run
```

This prints the Secret that would be created. Check that `type` is
`kubernetes.io/dockerconfigjson` and that the labels include
`config.oam.dev/type: demo-image-registry`.

## 4. Create the config

```bash
vela config create demo-registry \
  -t vela-system/demo-image-registry \
  -f localtest/vela-config/props-registry.yaml \
  -n default

vela config list -n default
kubectl get secret demo-registry -n default -o yaml
```

The Secret carries the rendered `.dockerconfigjson` plus an `input-properties`
key holding the original property values, which is what `vela config list` and
the UI read back.

Properties can also be passed inline instead of by file:

```bash
vela config create demo-registry-inline \
  -t vela-system/demo-image-registry \
  -n default \
  registry=index.docker.io username=vishal210893 password=not-a-real-token
```

## 5. Consume the config from an Application

```bash
vela up -f localtest/vela-config/app-consume-secret.yaml
vela status config-consumer -n default
kubectl get deploy web -n default -o jsonpath='{.spec.template.spec.imagePullSecrets}'
```

Expected: `[{"name":"demo-registry"}]`.

## 6. Create and read a config from a workflow

```bash
vela up -f localtest/vela-config/app-config-workflow.yaml
vela status config-workflow-demo -n default
kubectl get secret wf-registry -n default
```

The `create-config` step renders the same template inside the workflow, so no
`vela config create` is needed. The `read-config` step loads it back and exports
it as the `registryConfig` output for later steps.

## 7. Distribute the config to another namespace or cluster

```bash
vela config distribute demo-registry -n default -t dev
vela config list -n default
```

Distribution creates a hidden Application with a topology policy that copies the
Secret to the targets. Recall it with:

```bash
vela config distribute demo-registry -n default --recall
```

## 8. Clean up

```bash
vela delete config-workflow-demo -n default -y
vela delete config-consumer -n default -y
vela config delete demo-registry -n default -y
vela config delete demo-registry-inline -n default -y
vela config-template delete demo-image-registry -n vela-system -y
```
