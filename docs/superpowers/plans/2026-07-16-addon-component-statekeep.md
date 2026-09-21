# Addon-as-Component Auxiliary StateKeep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make auxiliary resources folded into an addon-as-component inner Application self-heal through the existing ResourceTracker and StateKeep path while preserving addon-authored apply-once policies.

**Architecture:** The addon renderer appends an explicit `apply-once` policy with `enable: false` only when the rendered addon Application has no apply-once policy. This prevents ResourceKeeper's legacy addon-label fallback from enabling application-wide apply-once, so inner ResourceTrackers retain raw manifests and periodic StateKeep can recreate deleted resources; generic ResourceKeeper production code and imperative addon behavior remain unchanged.

**Tech Stack:** Go 1.23, KubeVela Application and ResourceTracker APIs, controller-runtime fake client, Testify, Kubernetes/k3d, Markdown, static HTML with embedded JSON.

## Global Constraints

- Preserve every explicit addon-authored `apply-once` policy, whether enabled or disabled.
- Do not change the global `ApplyOnce` feature gate or the imperative `vela addon enable` path.
- Keep `app.oam.dev/last-applied-configuration: skip` on the rendered inner Application.
- Do not add dynamic resource watches, owner references, or a second reconciler.
- Use `v1alpha1.ApplyOncePolicyType` instead of duplicating the `apply-once` string in production code.
- Do not modify `pkg/resourcekeeper` production behavior; add only regression coverage there.
- Do not modify generated `charts/vela-core/templates/defwithtemplate/addon.yaml`; the behavior belongs in the renderer.
- Do not stage or revert unrelated dirty-worktree files, including generated deepcopy files and `charts/vela-core/templates/addon_registry.yaml`.
- Preserve malformed explicit apply-once input so normal Application validation reports it.
- Raw ResourceTracker storage is intentional. Record the fixed Terraform AWS and FluxCD tracker sizes; use the existing `ZstdResourceTracker` feature only if natural manifests approach API or etcd limits, and never fall back silently to metadata-only tracking.

---

## File Structure

- Modify `pkg/addon/service/renderer.go`: inject the default disabled apply-once policy.
- Modify `pkg/addon/service/renderer_test.go`: drive injection, preservation, collision, and idempotence behavior.
- Modify `pkg/resourcekeeper/resourcekeeper_test.go`: lock the existing explicit-policy override contract.
- Modify `docs/design/addon-as-component/{HLD.md,LLD.md,RESOURCE-TRACKERS.md}`: describe the post-folding ownership and healing model.
- Modify `docs/design/addon-as-component/index.html`: mechanically refresh embedded Markdown JSON without changing the UI.

---

### Task 1: Lock the ResourceKeeper Override Contract

**Files:**
- Modify: `pkg/resourcekeeper/resourcekeeper_test.go`
- Test: `pkg/resourcekeeper/resourcekeeper_test.go`

**Interfaces:**
- Consumes: `NewResourceKeeper(context.Context, client.Client, *v1beta1.Application) (ResourceKeeper, error)` and `(*resourceKeeper).Dispatch`.
- Produces: Characterization coverage proving explicit `apply-once: {enable: false}` on an addon-labeled Application stores `ManagedResource.Data`.

- [ ] **Step 1: Add test imports**

```go
"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

"github.com/oam-dev/kubevela/apis/core.oam.dev/v1alpha1"
```

- [ ] **Step 2: Add the characterization test after `TestNewResourceKeeper`**

```go
func TestAddonExplicitDisabledApplyOnceKeepsRawResourceData(t *testing.T) {
	r := require.New(t)
	cli := fake.NewClientBuilder().WithScheme(common.Scheme).Build()
	app := &v1beta1.Application{ObjectMeta: v1.ObjectMeta{
		Name: "addon-component-test", Namespace: "default", Generation: 1,
		Labels: map[string]string{oam.LabelAddonName: "test-addon"},
	}}
	app.Spec.Policies = []v1beta1.AppPolicy{{
		Name: "addon-component-state-keep", Type: v1alpha1.ApplyOncePolicyType,
		Properties: &runtime.RawExtension{Raw: []byte(`{"enable":false}`)},
	}}

	keeper, err := NewResourceKeeper(context.Background(), cli, app)
	r.NoError(err)
	rk := keeper.(*resourceKeeper)
	r.NotNil(rk.applyOncePolicy)
	r.False(rk.applyOncePolicy.Enable)

	cm := &unstructured.Unstructured{Object: map[string]interface{}{}}
	cm.SetGroupVersionKind(corev1.SchemeGroupVersion.WithKind("ConfigMap"))
	cm.SetName("statekeep-data-test")
	cm.SetNamespace("default")
	cm.Object["data"] = map[string]interface{}{"expected": "retained"}

	r.NoError(rk.Dispatch(context.Background(), []*unstructured.Unstructured{cm}, nil))
	r.NotNil(rk._currentRT)
	r.Len(rk._currentRT.Spec.ManagedResources, 1)
	r.NotNil(rk._currentRT.Spec.ManagedResources[0].Data)
}
```

- [ ] **Step 3: Run the characterization and legacy-fallback tests**

```bash
go test ./pkg/resourcekeeper -run 'TestNewResourceKeeper|TestAddonExplicitDisabledApplyOnceKeepsRawResourceData' -count=1
```

Expected: PASS. The new test captures existing behavior; `TestNewResourceKeeper` continues proving the implicit enabled fallback when no explicit policy exists.

- [ ] **Step 4: Commit the contract test**

```bash
git add pkg/resourcekeeper/resourcekeeper_test.go
git diff --cached --check
git commit -m "test: cover addon state keep policy override"
```

Expected staged scope: only `pkg/resourcekeeper/resourcekeeper_test.go`.

---

### Task 2: Inject the Disabled Policy in the Addon Renderer

**Files:**
- Modify: `pkg/addon/service/renderer.go`
- Modify: `pkg/addon/service/renderer_test.go`
- Test: `pkg/addon/service/renderer_test.go`

**Interfaces:**
- Consumes: unstructured Application maps and `v1alpha1.ApplyOncePolicyType`.
- Produces: `ensureAddonComponentStateKeepPolicy(map[string]interface{})`, called by `rendererImpl.resolveAndRender`.

- [ ] **Step 1: Add the failing test import and unit test**

Imports:

```go
"fmt"

"github.com/oam-dev/kubevela/apis/core.oam.dev/v1alpha1"
```

Add before `TestSuppressLastAppliedConfig`:

```go
func TestEnsureAddonComponentStateKeepPolicy(t *testing.T) {
	getPolicies := func(t *testing.T, app map[string]interface{}) []interface{} {
		t.Helper()
		spec, ok := app["spec"].(map[string]interface{})
		require.True(t, ok)
		policies, ok := spec["policies"].([]interface{})
		require.True(t, ok)
		return policies
	}

	t.Run("adds disabled policy", func(t *testing.T) {
		app := map[string]interface{}{}
		ensureAddonComponentStateKeepPolicy(app)
		policies := getPolicies(t, app)
		require.Len(t, policies, 1)
		assert.Equal(t, map[string]interface{}{
			"name": "addon-component-state-keep",
			"type": v1alpha1.ApplyOncePolicyType,
			"properties": map[string]interface{}{"enable": false},
		}, policies[0])
	})

	t.Run("preserves unrelated policies", func(t *testing.T) {
		topology := map[string]interface{}{
			"name": "deploy-local", "type": "topology",
			"properties": map[string]interface{}{"clusters": []interface{}{"local"}},
		}
		app := map[string]interface{}{
			"spec": map[string]interface{}{"policies": []interface{}{topology}},
		}
		ensureAddonComponentStateKeepPolicy(app)
		policies := getPolicies(t, app)
		require.Len(t, policies, 2)
		assert.Equal(t, topology, policies[0])
	})

	for _, enabled := range []bool{true, false} {
		t.Run(fmt.Sprintf("preserves explicit apply-once enable=%t", enabled), func(t *testing.T) {
			explicit := map[string]interface{}{
				"name": "addon-authored", "type": v1alpha1.ApplyOncePolicyType,
				"properties": map[string]interface{}{"enable": enabled},
			}
			app := map[string]interface{}{
				"spec": map[string]interface{}{"policies": []interface{}{explicit}},
			}
			ensureAddonComponentStateKeepPolicy(app)
			assert.Equal(t, []interface{}{explicit}, getPolicies(t, app))
		})
	}

	t.Run("preserves malformed explicit apply-once for validation", func(t *testing.T) {
		explicit := map[string]interface{}{
			"name": "invalid-addon-policy", "type": v1alpha1.ApplyOncePolicyType,
		}
		app := map[string]interface{}{
			"spec": map[string]interface{}{"policies": []interface{}{explicit}},
		}
		ensureAddonComponentStateKeepPolicy(app)
		assert.Equal(t, []interface{}{explicit}, getPolicies(t, app))
	})

	t.Run("uses deterministic name suffix", func(t *testing.T) {
		app := map[string]interface{}{"spec": map[string]interface{}{
			"policies": []interface{}{map[string]interface{}{
				"name": "addon-component-state-keep", "type": "garbage-collect",
				"properties": map[string]interface{}{},
			}},
		}}
		ensureAddonComponentStateKeepPolicy(app)
		policies := getPolicies(t, app)
		require.Len(t, policies, 2)
		assert.Equal(t, "addon-component-state-keep-2",
			policies[1].(map[string]interface{})["name"])
	})

	t.Run("is idempotent", func(t *testing.T) {
		app := map[string]interface{}{}
		ensureAddonComponentStateKeepPolicy(app)
		ensureAddonComponentStateKeepPolicy(app)
		assert.Len(t, getPolicies(t, app), 1)
	})
}
```

- [ ] **Step 2: Run the test and confirm RED**

```bash
go test ./pkg/addon/service -run TestEnsureAddonComponentStateKeepPolicy -count=1
```

Expected: compile failure containing `undefined: ensureAddonComponentStateKeepPolicy`.

- [ ] **Step 3: Add the production import and helper**

Import:

```go
"github.com/oam-dev/kubevela/apis/core.oam.dev/v1alpha1"
```

Add near `suppressLastAppliedConfig`:

```go
const addonComponentStateKeepPolicyName = "addon-component-state-keep"

// ensureAddonComponentStateKeepPolicy disables the legacy implicit apply-once
// behavior for component-installed addons unless the addon declares its own.
func ensureAddonComponentStateKeepPolicy(m map[string]interface{}) {
	spec, ok := m["spec"].(map[string]interface{})
	if !ok {
		spec = map[string]interface{}{}
		m["spec"] = spec
	}
	policies, _ := spec["policies"].([]interface{})
	usedNames := make(map[string]struct{}, len(policies))
	for _, item := range policies {
		policy, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		if policyType, _ := policy["type"].(string); policyType == v1alpha1.ApplyOncePolicyType {
			return
		}
		if name, _ := policy["name"].(string); name != "" {
			usedNames[name] = struct{}{}
		}
	}

	name := addonComponentStateKeepPolicyName
	for suffix := 2; ; suffix++ {
		if _, found := usedNames[name]; !found {
			break
		}
		name = fmt.Sprintf("%s-%d", addonComponentStateKeepPolicyName, suffix)
	}
	spec["policies"] = append(policies, map[string]interface{}{
		"name": name,
		"type": v1alpha1.ApplyOncePolicyType,
		"properties": map[string]interface{}{"enable": false},
	})
}
```

- [ ] **Step 4: Call the helper in `resolveAndRender`**

```go
appendAuxComponents(appMap, groups)
ensureAddonComponentStateKeepPolicy(appMap)
sanitizeManifest(appMap)
suppressLastAppliedConfig(appMap)
```

Do not change `suppressLastAppliedConfig`; it solves the independent annotation-size failure.

- [ ] **Step 5: Extend `TestRenderAddonReturnsApplicationWithComponents`**

After its component assertion, add:

```go
policies, ok := spec["policies"].([]interface{})
require.True(t, ok, "spec.policies must be a []interface{}")
var found bool
for _, item := range policies {
	policy, ok := item.(map[string]interface{})
	if ok && policy["type"] == v1alpha1.ApplyOncePolicyType {
		assert.Equal(t, map[string]interface{}{"enable": false}, policy["properties"])
		found = true
	}
}
assert.True(t, found, "rendered addon must disable implicit apply-once")
```

- [ ] **Step 6: Format and confirm GREEN**

```bash
gofmt -w pkg/addon/service/renderer.go pkg/addon/service/renderer_test.go
go test ./pkg/addon/service -run 'TestEnsureAddonComponentStateKeepPolicy|TestSuppressLastAppliedConfig|TestAppendAuxComponents' -count=1
```

Expected: PASS.

- [ ] **Step 7: Run every affected package**

```bash
make envtest
KUBEBUILDER_ASSETS="$(./bin/setup-envtest use 1.31.0 -p path)" \
  go test ./pkg/addon/service ./pkg/resourcekeeper ./pkg/appfile -count=1
git diff --check
```

Expected: all packages PASS; whitespace check emits no output.

- [ ] **Step 8: Commit only the renderer change**

```bash
git add pkg/addon/service/renderer.go pkg/addon/service/renderer_test.go
git diff --cached --name-status
git diff --cached --check
git commit -m "fix(addon): keep component auxiliaries reconciled"
```

Expected staged scope: exactly the two renderer files.

---

### Task 3: Verify StateKeep and Large-Addon Behavior in k3d

**Files:**
- Verify: existing Terraform AWS component Application
- Verify: `localtest/addon-component/fluxcd.yaml`

**Interfaces:**
- Consumes: rebuilt local `vela-core`, Application resync, and raw inner ResourceTracker manifests.
- Produces: live evidence that `aws-mq` is recreated and FluxCD avoids the annotation-size regression.

- [ ] **Step 1: Restart IntelliJ `CORE DEBUG` from the implementation commit**

Retain:

```text
--dev-logs=false --application-re-sync-period=20s
```

Expected: the local process starts and reconciles `k3d-kubevela`.

- [ ] **Step 2: Force the wrapping Terraform workflow to rerender**

```bash
vela workflow restart comp-terraform-aws -n vela-system
POLICY_ENABLED=""
for attempt in {1..20}; do
  sleep 2
  POLICY_ENABLED=$(kubectl get application.core.oam.dev addon-terraform-aws -n vela-system -o json \
    | jq -r '.spec.policies[]? | select(.type == "apply-once") | .properties.enable')
  if [[ "$POLICY_ENABLED" == "false" ]]; then break; fi
done
test "$POLICY_ENABLED" = "false"
```

Expected: `Successfully restart workflow: comp-terraform-aws`.

- [ ] **Step 3: Verify the inner generated policy**

```bash
kubectl get application.core.oam.dev addon-terraform-aws -n vela-system -o json \
  | jq '.spec.policies[] | select(.type == "apply-once")'
```

Expected: policy name `addon-component-state-keep` with `properties.enable: false`.

- [ ] **Step 4: Locate the current tracker and verify `aws-mq` raw data**

```bash
INNER_RT=""
HAS_RAW=""
for attempt in {1..20}; do
  sleep 2
  INNER_GENERATION=$(kubectl get application.core.oam.dev addon-terraform-aws -n vela-system -o jsonpath='{.metadata.generation}')
  INNER_RT=$(kubectl get resourcetrackers.core.oam.dev -o json | jq -r \
    --arg app addon-terraform-aws --argjson generation "$INNER_GENERATION" \
    '.items[] | select(.metadata.labels["app.oam.dev/name"] == $app and .spec.type == "versioned" and .spec.applicationGeneration == $generation) | .metadata.name')
  if [[ -n "$INNER_RT" ]]; then
    HAS_RAW=$(kubectl get resourcetracker.core.oam.dev "$INNER_RT" -o json \
      | jq -r '.spec.managedResources[]? | select(.kind == "ComponentDefinition" and .name == "aws-mq") | has("raw")')
  fi
  if [[ "$HAS_RAW" == "true" ]]; then break; fi
done
test -n "$INNER_RT"
test "$HAS_RAW" = "true"
kubectl get resourcetracker.core.oam.dev "$INNER_RT" -o json \
  | jq '.spec.managedResources[] | select(.kind == "ComponentDefinition" and .name == "aws-mq") | {name, hasRaw: has("raw")}'
```

Expected: `hasRaw` is `true`.

- [ ] **Step 5: Delete `aws-mq` and prove recreation**

```bash
OLD_UID=$(kubectl get componentdefinition.core.oam.dev aws-mq -n vela-system -o jsonpath='{.metadata.uid}')
kubectl delete componentdefinition.core.oam.dev aws-mq -n vela-system --wait=true
NEW_UID=""
for attempt in {1..20}; do
  sleep 2
  NEW_UID=$(kubectl get componentdefinition.core.oam.dev aws-mq -n vela-system --ignore-not-found -o jsonpath='{.metadata.uid}')
  if [[ -n "$NEW_UID" && "$NEW_UID" != "$OLD_UID" ]]; then break; fi
done
test -n "$NEW_UID"
test "$NEW_UID" != "$OLD_UID"
printf 'old=%s new=%s\n' "$OLD_UID" "$NEW_UID"
```

Expected: recreation within 40 seconds with a new UID.

- [ ] **Step 6: Capture tracker size and retained entry**

```bash
kubectl get resourcetracker.core.oam.dev "$INNER_RT" -o json | wc -c
kubectl get resourcetracker.core.oam.dev "$INNER_RT" -o json \
  | jq '.spec.managedResources[] | select(.name == "aws-mq") | {name, hasRaw: has("raw")}'
```

Expected: API read succeeds and the entry remains raw-backed.

- [ ] **Step 7: Reconcile FluxCD and verify the independent sentinel**

```bash
kubectl apply -f localtest/addon-component/fluxcd.yaml
FLUX_PHASE=""
for attempt in {1..40}; do
  sleep 3
  FLUX_PHASE=$(kubectl get application.core.oam.dev addon-fluxcd -n vela-system \
    --ignore-not-found -o jsonpath='{.status.status}')
  if [[ "$FLUX_PHASE" == "running" ]]; then break; fi
done
test "$FLUX_PHASE" = "running"
kubectl get application.core.oam.dev addon-fluxcd -n vela-system -o json \
  | jq '{phase: .status.status, lastApplied: .metadata.annotations["app.oam.dev/last-applied-configuration"], applyOnce: [.spec.policies[] | select(.type == "apply-once")]}'
```

Expected: phase reaches `running`, `lastApplied` is `skip`, apply-once is disabled, and no `metadata.annotations: Too long` error occurs.

- [ ] **Step 8: Verify that an explicit enabled apply-once policy is honored**

Create an isolated addon-labeled probe whose policy is explicit package-equivalent input:

```bash
kubectl apply -f - <<'EOF'
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: addon-explicit-apply-once-probe
  namespace: vela-system
  labels:
    addons.oam.dev/name: explicit-apply-once-probe
spec:
  policies:
    - name: addon-authored
      type: apply-once
      properties:
        enable: true
  components:
    - name: probe
      type: k8s-objects
      properties:
        objects:
          - apiVersion: v1
            kind: ConfigMap
            metadata:
              name: addon-explicit-apply-once-probe
              namespace: vela-system
            data:
              expected: apply-once
EOF
for attempt in {1..20}; do
  sleep 2
  PROBE_PHASE=$(kubectl get application.core.oam.dev addon-explicit-apply-once-probe \
    -n vela-system -o jsonpath='{.status.status}')
  if [[ "$PROBE_PHASE" == "running" ]]; then break; fi
done
test "$PROBE_PHASE" = "running"
PROBE_RT=$(kubectl get resourcetrackers.core.oam.dev -o json | jq -r \
  '.items[] | select(.metadata.labels["app.oam.dev/name"] == "addon-explicit-apply-once-probe" and .spec.type == "versioned") | .metadata.name')
kubectl get resourcetracker.core.oam.dev "$PROBE_RT" -o json \
  | jq -e '.spec.managedResources[] | select(.name == "addon-explicit-apply-once-probe") | has("raw") == false'
kubectl delete configmap addon-explicit-apply-once-probe -n vela-system --wait=true
sleep 25
test -z "$(kubectl get configmap addon-explicit-apply-once-probe -n vela-system --ignore-not-found -o name)"
kubectl delete application.core.oam.dev addon-explicit-apply-once-probe -n vela-system --wait=true
```

Expected: the tracker entry is metadata-only and the deleted ConfigMap stays absent, proving explicit enabled apply-once remains authoritative. The probe Application is removed afterward.

- [ ] **Step 9: Inspect recent regression events**

```bash
kubectl get events -n vela-system --sort-by=.metadata.creationTimestamp \
  | rg 'addon-terraform-aws|addon-fluxcd|StateKeep|Too long' | tail -n 40
```

Expected: no new StateKeep or annotation-size failure for the verified Applications.

---

### Task 4: Align the Design Documentation

**Files:**
- Modify: `docs/design/addon-as-component/HLD.md`
- Modify: `docs/design/addon-as-component/LLD.md`
- Modify: `docs/design/addon-as-component/RESOURCE-TRACKERS.md`
- Modify: `docs/design/addon-as-component/index.html`

**Interfaces:**
- Consumes: verified ownership and measurements from Task 3.
- Produces: source Markdown and embedded HTML content describing the same fixed architecture.

- [ ] **Step 1: Correct HLD ownership and flow**

Replace separate `outputs` ownership with:

```text
comp-<addon> versioned RT -> Application/addon-<addon>
Application/addon-<addon> -> addon workloads + auxiliary k8s-objects components
inner root/versioned RTs -> raw desired manifests for both groups
```

Add:

```markdown
**Component installs opt into StateKeep.** Rendered addon Applications carry an
explicit disabled `apply-once` policy unless the addon package declares its own.
This bypasses the legacy addon-label fallback, retains raw desired manifests in
the inner ResourceTracker, and lets periodic StateKeep heal deleted auxiliaries.
Imperative addon installs keep their legacy behavior.
```

- [ ] **Step 2: Correct LLD examples and document both fixes**

Show the current render sequence:

```go
app, aux := pkgaddon.RenderApp(ctx, installPkg, r.client(), req.Properties)
groups := r.auxComponents(ctx, installPkg, req.Properties)
groups = append(groups, auxComponent{name: "addon-auxiliaries", objects: aux})
appMap := toUnstructured(app)
appendAuxComponents(appMap, groups)
ensureAddonComponentStateKeepPolicy(appMap)
sanitizeManifest(appMap)
suppressLastAppliedConfig(appMap)
return &api.AddonResult{Application: appMap}
```

Document the existing fallback:

```go
if h.applyOncePolicy == nil && metav1.HasLabel(h.app.ObjectMeta, oam.LabelAddonName) {
	h.applyOncePolicy = &v1alpha1.ApplyOncePolicySpec{Enable: true}
}
```

Explain that explicit `enable: false` prevents `Dispatch` from applying `MetaOnlyOption` and prevents StateKeep from returning early. The `last-applied-configuration: skip` sentinel separately prevents the 256 KiB annotation failure. Document `ZstdResourceTracker` as the existing mitigation if measured raw tracker sizes approach API or etcd limits; metadata-only tracking is not an acceptable size fallback because it disables healing.

- [ ] **Step 3: Rewrite ResourceTracker claims from Task 3 evidence**

Use this ownership table and insert measured Terraform AWS/FluxCD byte counts:

```markdown
| Owner | Tracker | Contents |
|-------|---------|----------|
| Wrapping `comp-<addon>` Application | versioned RT | One rendered inner addon Application |
| Inner `addon-<addon>` Application | root/versioned RTs according to GC policy | Addon workloads plus folded auxiliary resources, stored with raw desired data |
```

Include the generated policy, configured 20-second interval, and `aws-mq` old/new UID evidence. Remove old per-resource sizes unless remeasured from the fixed cluster.

- [ ] **Step 4: Refresh only the HTML `docs-data` payload**

```bash
node <<'NODE'
const fs = require('fs');
const base = 'docs/design/addon-as-component';
const docs = [
  { id: 'hld', label: 'HLD', file: 'HLD.md' },
  { id: 'lld', label: 'LLD', file: 'LLD.md' },
  { id: 'resource-trackers', label: 'ResourceTrackers', file: 'RESOURCE-TRACKERS.md' },
].map((doc) => ({ ...doc, markdown: fs.readFileSync(`${base}/${doc.file}`, 'utf8') }));
const htmlPath = `${base}/index.html`;
const html = fs.readFileSync(htmlPath, 'utf8');
const payload = JSON.stringify(docs).replace(/</g, '\\u003c');
const marker = /(<script id="docs-data" type="application\/json">)[\s\S]*?(<\/script>)/;
if (!marker.test(html)) throw new Error('docs-data script not found');
fs.writeFileSync(htmlPath, html.replace(marker,
  (_match, open, close) => `${open}${payload}${close}`));
NODE
```

Do not change CSS, layout, or client-side behavior.

- [ ] **Step 5: Verify source/HTML parity and stale-claim removal**

```bash
node <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('docs/design/addon-as-component/index.html', 'utf8');
const match = html.match(/<script id="docs-data" type="application\/json">([\s\S]*?)<\/script>/);
if (!match) throw new Error('docs-data script not found');
const docs = JSON.parse(match[1]);
for (const doc of docs) {
  const source = fs.readFileSync(`docs/design/addon-as-component/${doc.file}`, 'utf8');
  if (doc.markdown !== source) throw new Error(`${doc.file} is out of sync`);
}
console.log('HTML docs-data matches all Markdown sources');
NODE
! rg -n 'output \+ outputs|return output \+ outputs|AddonResult \(application, resources\)' \
  docs/design/addon-as-component/{HLD.md,LLD.md,RESOURCE-TRACKERS.md}
rg -n 'addon-component-state-keep|apply-once|StateKeep|k8s-objects' \
  docs/design/addon-as-component/{HLD.md,LLD.md,RESOURCE-TRACKERS.md}
git diff --check -- docs/design/addon-as-component
```

Expected: parity success, no obsolete matches, required concepts present, no whitespace errors.

- [ ] **Step 6: Commit exactly the four documentation files**

```bash
git add docs/design/addon-as-component/HLD.md \
  docs/design/addon-as-component/LLD.md \
  docs/design/addon-as-component/RESOURCE-TRACKERS.md \
  docs/design/addon-as-component/index.html
git diff --cached --name-status
git diff --cached --check
git commit -m "docs: align addon component state keep design"
```

Expected staged scope: exactly those four files.

---

### Task 5: Final Verification and Review

**Files:**
- Verify: all implementation, test, and documentation files above

**Interfaces:**
- Consumes: committed code, cluster evidence, and corrected documentation.
- Produces: final completion evidence without unrelated worktree changes.

- [ ] **Step 1: Run all affected tests and whitespace checks**

```bash
make envtest
KUBEBUILDER_ASSETS="$(./bin/setup-envtest use 1.31.0 -p path)" \
  go test ./pkg/addon/service ./pkg/resourcekeeper ./pkg/appfile -count=1
git diff --check
```

Expected: PASS and no whitespace output.

- [ ] **Step 2: Audit implementation scope**

```bash
git log --oneline -7
git diff e7a06a7b8..HEAD -- pkg/addon/service/renderer.go \
  pkg/addon/service/renderer_test.go pkg/resourcekeeper/resourcekeeper_test.go
git status --short
```

Expected: one ResourceKeeper test-only change, one renderer behavior change, documentation updates, and untouched unrelated dirty files.

- [ ] **Step 3: Request code review**

Invoke `superpowers:requesting-code-review` with the design spec, this plan, implementation commits, test output, tracker sizes, and old/new `aws-mq` UIDs. Resolve every correctness finding before claiming completion.
