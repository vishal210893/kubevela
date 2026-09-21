# Design: `vela module publish` (ECR/OCI) (GWCP-106685)

## Context

Publishing is the producer half of the module loop. An author has a `modules/<name>/` tree on
disk; `vela module publish` validates it and pushes it as an OCI artifact so the `type: module`
component can fetch and install it later. ECR is the target the team is standardising on; ECR is
an OCI registry, so one push path covers ECR, GHCR, Harbor, and a local registry.

Git-catalog publish is out of scope. Fetch keeps git for reading a pre-existing catalog.

Upstream spec: `specs/oss-kubevela/module-registry/gwcp-106685-module-publish/`
(`requirements.md`, `design.md`, `tasks.md`). Deviations are recorded at the end.

## What the consumer already demands

Fetch is the binding constraint, not a preference. `pkg/module/service/fetch.go:153` pulls a
module through `addon.PullOCIChartFiles`, which is the Helm registry client, and
`fetch.go:124` strips the prefix `<moduleName>/` from every returned path. So the artifact
must be a Helm chart whose chart name is the module name and whose files sit under that one
top-level directory. An artifact in any other shape fetches as an empty module.

Second constraint: the chart version is the tag, and Helm requires semver. The parser already
requires strict semver for `_module.cue version` (`pkg/module/validate.go:44`), so the two
rules agree.

## Artifact structure

What `vela addon push` produces today, for comparison (`pkg/addon/oci_registry.go:96`,
`pkg/addon/oci_catalog.go:174`):

```
<host>/<prefix>/<addonName>:<version>
  config      Chart.yaml as JSON        (application/vnd.cncf.helm.config.v1+json)
  layer[0]    chart .tgz                (application/vnd.cncf.helm.chart.content.v1.tar+gzip)
  annotations Helm defaults only
  tgz         <addonName>/{Chart.yaml,metadata.yaml,template.yaml,definitions/,resources/}
plus, on every push:
<host>/<prefix>/kubevela-addon-catalog:<semver>   layer holds catalog.json (addon index)
```

What publish produces for a module:

```
<account>.dkr.ecr.<region>.amazonaws.com/<prefix>/s3:1.0.0
  config      generated Chart.yaml as JSON: name s3, version 1.0.0, type library
  layer[0]    chart .tgz
  annotations org.opencontainers.image.{title,version,created}   (Helm)
              modules.oam.dev/module          s3
              modules.oam.dev/lines           v1,v2
              modules.oam.dev/enabled-lines   v1
  tgz         s3/Chart.yaml          the only file publish adds
              s3/_module.cue
              s3/auxiliary/xrd.yaml
              s3/v1/_version.cue
              s3/v1/auxiliary/composition.yaml
              s3/v1/definitions/bucket.cue
```

Three rules inside that, each of which prevents a specific failure:

- **Chart name comes from `_module.cue module`, never from the directory argument.** Fetch strips
  `<moduleName>/` using the name it looked the module up by. If publish named the chart after the
  directory and the two differed, every file would be dropped on pull and the module would fetch
  as empty. This is the same divergence class as the bug the deploy review caught in
  GWCP-106942.
- **Tag comes from `_module.cue version`,** or `--version` when given. `--version` must still be
  semver, and it does not bypass immutability.
- **`Chart.yaml` is written into a temporary copy of the tree,** never into the author's
  directory. A module tree is git-tracked source. `vela addon push` mutates the source directory
  (`pkg/addon/utils.go:413`); publish leaves it byte-identical whether the push succeeds or fails.

The copy skips `.git/` and `.helmignore`. The `.helmignore` case matters: Helm's directory
loader applies `ignore.Empty()` only when no `.helmignore` is present
(`helm/pkg/chart/loader/directory.go:55`), so a stray ignore file in a module tree would
silently drop the author's own files from the artifact. A `Chart.yaml` already in the tree is
overwritten in the copy. A `templates/` directory is a documented non-goal: Helm would
reinterpret it, and modules do not ship one.

Publish writes no `kubevela-addon-catalog` artifact. Modules are not addons, module fetch never
reads that index, and writing to it would surface modules in `vela addon list`.

## Annotations, and why not tags

Annotations live in the manifest JSON, which is content-addressed: the manifest digest is the
hash of those exact bytes, so a registry cannot rewrite them without breaking its own integrity
check. Helm copies `Chart.yaml annotations` into the manifest verbatim
(`helm/pkg/registry/util.go:176`), so this needs no new push code.

Fetch and render need to know which API lines a version ships and which are enabled. With
annotations that is one manifest request; without them it means downloading and parsing the
tarball.

Cost, stated plainly: the ECR console does not display annotations, and `describe-images` does
not return them. Reading them takes `aws ecr batch-get-image ... --query 'images[0].imageManifest'`
or any OCI client. The rejected alternative was stamping extra tags such as `1.0.0-v1` for
console visibility; it creates tags that are not releases, and Helm's semver tag listing would
return them as candidate versions.

## Command surface

`references/cli/module-publish.go`, mounted on the `vela module` group next to `registry` and
`deploy` (`references/cli/module-registry.go:63`):

```
vela module publish <dir> [--registry <name>] [--version <tag>] [--force] [--dry-run]
vela module publish <dir> <oci-ref>            [--version <tag>] [--force] [--dry-run]
```

- `<dir>` is the module directory. Required.
- `--registry <name>` resolves a configured module registry from the cluster. Mutually exclusive
  with the positional reference.
- `<oci-ref>` targets a registry directly, with or without the `oci://` scheme, so an ECR host
  can be pasted as-is: `123456789012.dkr.ecr.us-west-2.amazonaws.com/modules`.
- `--version` overrides the tag. Must be semver. Does not bypass immutability.
- `--force` allows overwriting an existing tag.
- `--dry-run` prints the target reference, the tag, and the annotations, and pushes nothing.
  Useful before a first push to a shared ECR registry.
- `--username`, `--password`, `--password-stdin` override the credential chain, matching
  `vela module registry add`.

Neither `--registry` nor a positional reference means "resolve the default registry", which needs
cluster access; a positional reference does not.

## Flow

1. `pkgmodule.ParseModuleDir(dir)`. On error, exit non-zero, push nothing (Requirement 1.2, 5.2).
2. Resolve the target. `--registry` or the default goes through
   `module.ResolveRegistry(ctx, module.NewStore(cli), name)`; a git registry is rejected with
   "publish supports OCI/ECR only" (Requirement 1.3). A positional reference becomes an
   `addon.Registry{OCI: &addon.OCIAddonSource{URL: ref}}` with no cluster call.
3. Decide the tag: `Module.Version`, or `--version`.
4. Package: copy the tree to a temp dir, write the generated `Chart.yaml`, load it with Helm's
   directory loader, save the archive.
5. Immutability check: list the repository's tags; if the tag exists and `--force` is absent,
   reject and tell the author to bump `_module.cue version` (Requirement 3).
6. Push. Report the pushed reference.

Steps 1 through 3 touch no registry, so a bad tree or a git target fails with nothing uploaded.

## Placement

- `pkg/module/publish.go` holds packaging: the temp-copy, the generated chart metadata, the
  annotation map, the tag decision. Pure and unit-testable without a registry.
- `pkg/addon/oci_push.go` adds `PushOCIChart` and `OCIChartTagExists`, mirroring the exported
  `PullOCIChartFiles` (`pkg/addon/oci_registry.go:284`) and reusing the unexported `ociRepoRef`
  and `newOCIClient`.
- `references/cli/module-publish.go` holds flags, argument rules, and error text.

`pkg/addon.PushCmd` is not reused. Its OCI path calls `MakeChartCompatible`, which rejects any
directory without a `metadata.yaml` (`pkg/addon/push.go:228`, `pkg/addon/utils.go:389`), writes
`Chart.yaml` into the source tree, and updates the addon catalog (`push.go:271`). Teaching it a
module mode would mean conditionals through all three.

## Auth

Nothing new. Helm's registry client is built with `dockerauth.NewClientWithDockerFallback`
(`helm/pkg/registry/client.go:84`), so it reads `~/.docker/config.json`, including `credsStore`
and `credHelpers`. That means `docker-credential-ecr-login` and
`aws ecr get-login-password | docker login` both authenticate an ECR push with no code of ours
involved (Requirement 5.1). `--username`/`--password` override, and `helm registry login`
credentials are honoured too, since that is the same client's own store.

One shared change is needed. `ociRegistryLocation` (`pkg/addon/oci_registry.go:82`) understands
only `oci://` and bare hosts, so an `http://` URL parses as host `http:` today. Publish extends it
to strip `http://` and `https://` as well, and `newOCIClient` adds Helm's
`registry.ClientOptPlainHTTP()` when the host is loopback (`localhost`, `127.0.0.1`, `::1`). Both
changes are additive: no currently valid input changes meaning, no function signature changes, and
no call site churn. This is what lets the in-process registry test push and pull over HTTP, and it
also unblocks a developer registry running on localhost.

## ECR specifics

- **The repository must already exist.** ECR does not create one on push unless the registry has
  a creation template. Publish maps the registry's `NAME_UNKNOWN` / 404 into a message naming the
  repository and the fix. It does not call `CreateRepository`: that would mean an `aws-sdk-go`
  dependency, `ecr:CreateRepository` for every publisher, and a CLI creating cloud resources.
- **Tag immutability is also an ECR setting.** On an `IMMUTABLE` repository the registry rejects
  a re-push regardless of `--force`. The error says so, rather than letting `--force` look broken.
- Authorization tokens expire (12 hours). That is the credential helper's job, not ours.

## Error handling

- Parser errors propagate verbatim; they already name the file and the field.
- Registry resolution errors propagate from `ResolveRegistry`, which names the configured
  registries.
- The immutability rejection names the reference, the existing tag, and the `_module.cue version`
  bump.
- A missing repository, an auth failure, and an immutable-tag rejection each get their own
  message; the raw registry error is wrapped, not replaced.
- Every failure exits non-zero and leaves nothing pushed and nothing written in the source tree.

## Testing

Unit, no network:

- Packaging: archive contains every source file under `s3/`, plus `Chart.yaml`; `.helmignore` and
  `.git/` are excluded; the source directory is unchanged afterwards.
- Round-trip (Requirement 4.2): pack, then load the archive with `loader.LoadArchiveFiles`, strip
  the `s3/` prefix, `ParseModule`, and assert an equal `Module`, over both the `s3` and `minimal`
  fixtures.
- Annotations (Requirement 4.1): module, lines, and enabled-lines keys, lines sorted.
- Tag: from `_module.cue version`; `--version` overrides; a non-semver `--version` is rejected.
- Parser gate: an invalid tree pushes nothing, with the push seam asserting zero calls.
- Git registry target: rejected with the OCI-only message, nothing pushed.
- Immutability: an existing tag is rejected; `--force` proceeds; a repository with no tags
  proceeds.
- CLI: flag set, mutual exclusion of `--registry` and the positional reference, `--dry-run`
  output, and the command being mounted on `vela module`.

Live registry, in-process (`-tags integration`): serve `go-containerregistry/pkg/registry` on
`httptest`, publish the `s3` fixture over plain HTTP, then read the manifest back to assert the
tag and the annotations, and pull with `addon.PullOCIChartFiles` and `ParseModule` to assert an
equal `Module`. Docker is not required. This also fills the
`publishAndFetch` placeholder in `pkg/module/service/fetch_integration_test.go:64`.

Real ECR: the same assertions run when `MODULE_ECR_REGISTRY` is set, otherwise the test skips.
CI stays hermetic; the ECR acceptance criterion is exercised on demand.

## Deviations from the upstream spec

1. **The source tree is never modified.** The upstream design reuses the addon push path, which
   writes `Chart.yaml` into the module directory. Publish packages a temp copy instead.
2. **No addon catalog write,** which the addon OCI push does unconditionally.
3. **Chart name is taken from `_module.cue`, not the directory,** which the upstream design does
   not state and which fetch's prefix stripping requires.
4. **`--dry-run` added.** Not in the requirements. It prints the resolved reference, tag, and
   annotations without pushing, which is the cheapest way to check a shared ECR target before a
   first publish.
5. **`--registry` is optional.** With neither flag nor positional reference, `ResolveRegistry`
   applies its own defaulting rules, as `vela module deploy` does.
6. **Loopback registries are addressed over plain HTTP, and `http://`/`https://` URLs parse
   correctly, in shared `pkg/addon` code.** Needed for the in-process live test, additive for
   existing inputs.
7. **The live test uses an in-process registry rather than a `registry:2` container.** No docker
   daemon is available in the development container; the in-process server implements the same
   distribution API over real HTTP.

## Out of scope

- Git-catalog publish.
- Parsing and validating the tree (GWCP-105647) beyond calling the parser.
- Registry configuration (GWCP-106679) beyond calling the resolver.
- ECR repository provisioning.
- Signing and provenance.
- A module index artifact for listing modules in a registry.
