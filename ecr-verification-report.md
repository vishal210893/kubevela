# GWCP-106685 — ECR Verification Report

Date: 2026-08-21
Account: `776719623202` (gwre-ccs-scratch), region `us-west-2`, repo `modules/s3`
Cluster: k3d `k3d-kubevela` (reached from devcontainer via `host.docker.internal:<mapped-port>`, insecure-skip-tls-verify), vela-core running in user's IDE against that cluster.

## PASS

| # | Scenario | Command / path | Result |
|---|----------|-----------------|--------|
| 1 | STS identity + ECR reachability | `aws sts get-caller-identity`, `aws ecr describe-repositories` | Assumed role `gwre-insurer_operators_admin`; repo exists |
| 2 | Publish round trip (manifest + annotations) | `go test -tags integration ./pkg/module/... -run TestPublishRoundTripECR` | PASS — push via helm registry client, verify via go-containerregistry: `modules.oam.dev/module=s3`, `lines=v1`, `enabled-lines=v1` all present |
| 3 | Immutability guard | `vela module publish ... --registry ecr` (no `--force`, tag exists) | `Error: .../s3:1.0.0 is already published; ... or pass --force to overwrite` |
| 4 | `--version` override publish | `vela module publish ... --version 1.1.0` | Published distinct tag `1.1.0`; warns that `_module.cue` still declares `1.0.0` — tag ≠ embedded declared version |
| 5 | Non-semver tag rejected client-side | `vela module publish ... --version latest` | `Error: version "latest" in --version is not a valid semver` — fails before touching the network |
| 6 | Force overwrite | `vela module publish ... --force` | `Published .../s3:1.0.0` — old digest for that tag becomes untagged/orphaned in ECR (expected MUTABLE-tag behavior) |
| 7 | `--dry-run` makes no registry write | `vela module publish ... --version 9.9.9 --dry-run` | Printed target/annotations only; confirmed via `aws ecr list-images` — no `9.9.9` tag created |
| 8 | Version resolution (highest semver wins) | `go test -tags integration ./pkg/module/service/... -run TestFetchModule_RoundTrip` (`MODULE_OCI_REGISTRY` set, repo has `1.0.0`+`1.1.0`) | PASS — `FetchModule(ctx, reg, "s3")` (empty version) resolves and pulls successfully; parsed `mod.Version` reflects the artifact's *embedded* `_module.cue` value, not the OCI tag, confirming the tag/declared-version split from scenario 4 |
| 9 | Anonymous pull rejected | `curl https://.../v2/` (no auth), and go-containerregistry pull before `docker login` | `401 Unauthorized` both times — confirms ECR requires explicit credentials, no ambient IAM-role pull |
| 10 | Client-side credential chain, two independent stores | `aws ecr get-login-password \| helm registry login ...` then separately `\| docker login ...` | Helm push path reads `~/.config/helm/registry/config.json`; go-containerregistry's `authn.DefaultKeychain` (used for verification/pull in tests, and by anything using go-containerregistry directly) reads `~/.docker/config.json` only. **The two are not interchangeable** — logging into one does not satisfy the other |
| 11 | Nonexistent module — fast, clear failure | `vela module deploy doesnotexist-module --registry ecr -n default --timeout 30s` | Failed synchronously (no controller round-trip needed): `pull OCI chart: ... GET .../tags/list: 404: name unknown: The repository with name 'modules/doesnotexist-module' does not exist` — confirms `vela module deploy` calls `FetchModule` client-side before applying, not only in-cluster; no stray Application left behind |
| 12 | No silent version drift on existing deployments | `kubectl get application module-s3-deploy -o jsonpath='{.status.latestRevision.name}'` before/after publishing `1.1.0` | Stayed `module-s3-deploy-v1`, generation unchanged — publishing a new highest-semver tag does **not** retroactively move an already-applied module; re-resolution only happens on next spec change/redeploy, not on periodic self-healing reconcile |
| 13 | Registry entry + Secret token flow (from earlier session, reconfirmed) | `vela module registry update ecr --type oci --username AWS --password-stdin`; `kubectl get secret module-registry-ecr -n vela-system` | ConfigMap holds only `tokenSecretRef`; Secret `module-registry-ecr` holds the actual token; `module-s3-deploy` reached `Ready` end-to-end through the in-IDE controller using this path |

## FAILED FIRST, THEN FIXED (environment, not code)

- **k3d API unreachable** (`dial tcp ...: i/o timeout` / `connection refused`): kubeconfig's `server: https://0.0.0.0:<port>` is a bind address, not a connect target from inside the devcontainer, and the mapped port drifts across container/session restarts with no `docker.sock` available to query it. Fixed per-session by rewriting to `host.docker.internal:<port>` + `insecure-skip-tls-verify: true` (dropping `certificate-authority-data`, which conflicts with `insecure-skip-tls-verify`). **This is not durable** — expect to redo it if the k3d container restarts. No code-side fix exists for this; it's a devcontainer/network-topology limitation.
- **`AWS_PROFILE=''` in the container's shell init** caused `aws: [ERROR]: The config profile () could not be found` on every call until explicitly `unset`.

## NOT EXERCISED (documented from source, not tested live this session)

- **Non-semver tag pushed by other means** (raw `oras`/manual push bypassing the CLI's semver validation) being silently skipped by `resolveVersion` — validated by code (`pkg/addon/oci_registry.go:122-139`), not reproduced live (would need a non-CLI push path).
- **12-hour ECR token expiry mid-reconcile** on the controller side — the STS session used here is short-lived (~1h typical), not the 12h `get-login-password` token; expiry behavior itself wasn't forced.
- **Version pinning at deploy/fetch time** — confirmed absent (same finding as prior session): neither `vela module deploy` nor the controller's render path accepts a version; both always resolve highest semver. No regression, no new coverage needed — still a known gap, not this session's scope to close.

## Cleanup left for the user

- ECR repo `modules/s3` now has tags `1.0.0` (force-overwritten once) and `1.1.0`, plus one untagged orphaned digest from the overwrite. All test artifacts, safe to leave or delete at your discretion.
- `module-s3-deploy` / `module-s3` Applications still running in `k3d-kubevela` from this and the prior session's testing.
- Local `~/.config/helm/registry/config.json` and `~/.docker/config.json` now hold ECR credentials for `776719623202.dkr.ecr.us-west-2.amazonaws.com` (STS-derived, will stop working once that STS session expires).
- The STS session token you pasted in chat twice is now in this transcript in plaintext — treat it as burned once you're done; don't reuse it outside this test.
