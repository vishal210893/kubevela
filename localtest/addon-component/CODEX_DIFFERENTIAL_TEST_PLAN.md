# Differential test plan: addon-as-component vs `vela addon enable`

Hand-off for Codex. Goal: prove that installing an addon as a `type: addon`
component behaves the SAME as the baseline `vela addon enable` flow, across the
KubeVela addon catalog. Any difference is either a feature bug or an
intentional, documented divergence.

A ready-to-run automation script lives next to this file:
`localtest/addon-component/differential-test.sh`. Read this plan first, then run
or adapt the script.

---

## 0. Decisions already made (do not re-litigate)

These ambiguities from the original task have been resolved. Honor them.

- **Branch:** the feature lives on `feat/addon-component` (NOT
  `feat/kep-2.13-addon-types`, which was an earlier working name). Check out
  `feat/addon-component`.
- **Cluster tool:** k3d (two clusters are simple to script). kind works too; if
  you switch, keep the same two-cluster shape.
- **Scope:** start with a curated subset (fluxcd, velaux, dex, kruise-rollout,
  vela-workflow, and a couple more) to shake out the harness. Only after that is
  green, run `--all` to sweep the whole catalog. Do not open the run on the full
  catalog; a harness bug would waste the whole pass.
- **The Cluster B version-gate asymmetry (important):** Cluster B runs vela-core
  as a local out-of-cluster process, so the addon SystemRequirements check can't
  read an in-cluster vela-core version and would fail every addon. Cluster A
  (real `vela install`) passes that check. To keep the comparison apples-to-apples
  we set `skipVersionValidate: true` on every Cluster B fixture (this mirrors
  `vela addon enable --skip-version-validating`). Record it as a known asymmetry
  in the report; it is not a bug and must not be counted as a discrepancy.

## 1. What "the addon-as-component mechanism" actually is

There is no new CRD. An addon is applied as a normal Application containing one
component of `type: addon`:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: comp-<addon>
  namespace: vela-system
spec:
  components:
    - name: <addon>            # addon name; defaults to the component name
      type: addon
      properties:
        version: "<optional>"  # omit for latest
        registry: "<optional>" # omit for the default registry
        properties: {}         # addon parameters, if any
        skipVersionValidate: true   # required on Cluster B (see §0)
```

Applying it makes the controller render the addon's own Application as the
component output and create it as `addon-<addon>` in `vela-system`, plus the
addon's definitions/configmaps/secret. So BOTH mechanisms converge on the same
observable object: an `addon-<addon>` Application in `vela-system`. That is the
comparison anchor.

## 2. Environment (what the script builds)

- **Cluster A — baseline / source of truth.** `k3d cluster create`, then
  `vela install` (latest released CLI), so vela-core runs as a normal in-cluster
  deployment. Addons enabled with `vela addon enable <name>`.
- **Cluster B — feature.** `k3d cluster create`, then a manual install because
  there is NO `make core-install` target in this repo (the task's `make core
  install` / `make test install` do not exist). The real steps are:
  - CRDs: `kubectl apply --server-side -f charts/vela-core/crds/`
  - Definitions: `bash hack/utils/installdefinition.sh` (this is what
    `make def-install` runs)
  - The `addon` ComponentDefinition:
    `vela def apply vela-templates/definitions/internal/component/addon.cue -n vela-system`
  - Addon registry ConfigMap pointing at the official catalog.
  - Build + run vela-core as a LOCAL process:
    `CGO_ENABLED=0 go build -o /tmp/vela-core ./cmd/core` then
    `KUBECONFIG=<B> /tmp/vela-core --use-webhook=false --enable-leader-election=false --metrics-addr=0 --health-addr=:9441`
  - The local process reaches the k3d cluster through the kubeconfig k3d writes
    (its API server is published on a host port).
  - **Before any addon test, confirm the controller reconciles** by applying a
    trivial webservice Application and watching it reach `running`. The script
    does this (`diff-sanity`).

Prerequisites on PATH: `vela`, `k3d`, `kubectl`, `go`, `python3`, `curl`.

### Guard: renderer must be linked

If Cluster B addons all fail with `addon renderer not initialized`, the vela-core
binary was built without the addon render service. It registers via an `init()`
that only runs because of a blank import in `cmd/core/app/server.go`:
`_ "github.com/oam-dev/kubevela/pkg/addon/service"`. An IDE "optimize imports"
pass can silently drop it. The script asserts the symbol is present
(`go tool nm <bin> | grep -c pkg/addon/service` must be > 0) and aborts early if
not. If you hit this, restore the import and rebuild.

## 3. Addon enumeration

- Subset (default): the array `SUBSET` in the script.
- Full catalog (`--all`): `vela addon list` on Cluster A, first column. Use the
  SAME list for both clusters. (Alternatively read github.com/kubevela/catalog,
  but `vela addon list` against A is the least effort and matches what A can
  actually install.)
- Some addons need mandatory parameters and will fail on both clusters without
  them. That shows up as FAIL/FAIL (consistent), not a discrepancy. If you want
  those addons to actually install, add their parameters to both the
  `vela addon enable` args and the Cluster B fixture `properties`.

## 4. Per-addon execution (hard timeout, per cluster)

For each addon, independently on each cluster, with a hard 3–5 min timeout
(`PER_ADDON_TIMEOUT`, default 300s):

1. **Cluster A:** `vela addon enable <name> -y` (bounded by `timeout`), then poll
   `addon-<name>` in `vela-system`.
2. **Cluster B:** apply the `type: addon` Application above, then poll
   `addon-<name>` in `vela-system`.
3. **Health signal (same on both):** the `addon-<name>` Application reaches
   `status.status == running`. The script also treats `workflowFailed` as a clean
   FAIL. Neither within the window ⇒ TIMEOUT (distinct from FAIL). On A you can
   additionally run `vela addon status <name>`; for deeper health check the
   addon's Deployments/StatefulSets have `availableReplicas == desired` and no pod
   is CrashLoopBackOff.
4. **On FAIL or TIMEOUT, capture** the Application YAML, workflow step messages,
   and recent events to `diag-<A|B>-addon-<name>.txt`. Do not discard them.
5. A timeout on one cluster does NOT block the other — they are polled
   independently.

## 5. Classification

Per addon:
- **PASS / PASS** → MATCH, consistent, no action.
- **FAIL / FAIL** (or TIMEOUT/TIMEOUT) → MATCH, likely a pre-existing addon issue,
  not a component-mechanism bug.
- **PASS / FAIL** or **PASS / TIMEOUT** → DISCREPANCY, likely a feature bug. Flag.
- **FAIL / PASS** or **TIMEOUT / PASS** → DISCREPANCY, unexpected. Flag.
- Any TIMEOUT is rendered distinctly from FAIL, because a timeout may just mean
  "needs more time." Re-run a TIMEOUT row with a larger `PER_ADDON_TIMEOUT` before
  filing a bug.

## 6. Deliverables

1. **The script** (`differential-test.sh`) — re-runnable and idempotent: it
   reuses existing clusters, skips `vela install` if vela-core is already up,
   and tears down clusters + the local core on exit (`--keep` to retain).
2. **The markdown report** (`$WORK/differential-report.md`, default
   `/tmp/addon-diff/`):

   | Addon Name | Vela Install Result | Addon-as-Component Result | Match? | Notes / Error |
   |---|---|---|---|---|

3. **A discrepancy summary** section listing ONLY the DISCREPANCY rows (including
   TIMEOUT-driven ones), since those are the actionable items.

## 7. How to run

```bash
cd <repo-root>              # feat/addon-component
git checkout feat/addon-component

# curated subset first (recommended)
./localtest/addon-component/differential-test.sh

# once green, full catalog:
./localtest/addon-component/differential-test.sh --all

# keep clusters/core for manual poking afterwards:
./localtest/addon-component/differential-test.sh --keep

# explicit addon list:
./localtest/addon-component/differential-test.sh fluxcd velaux dex

# tunables:
PER_ADDON_TIMEOUT=420 WORK=/tmp/mydiff ./localtest/addon-component/differential-test.sh
```

## 8. Reporting back

Paste the ENTIRE `differential-report.md` (both tables). For every DISCREPANCY
row, also paste the matching `diag-*-addon-<name>.txt` (Application YAML +
workflow step messages + events) so the failure can be diagnosed without a
re-run. Do not summarize away the raw capture. End with one paragraph naming
which discrepancies look like real addon-as-component bugs versus environment/
parameter artifacts.

## 9. Ask first if

- An addon needs mandatory parameters you don't know (its `vela addon enable`
  prompts, or FAIL/FAIL with a "missing required parameter" message) — ask before
  inventing values.
- `vela install` on Cluster A pins a version whose catalog differs from the
  branch's expectations — ask which released vela version to baseline against.
- You cannot make the local Cluster B core reach the k3d API server (kubeconfig
  server address / host-port issue) — report the exact error rather than guessing.
