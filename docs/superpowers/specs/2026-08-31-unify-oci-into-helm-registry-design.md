# Fold the OCI addon registry into the Helm registry

Date: 2026-08-31
Branch: `feat/addon-component`
Status: proposed

## Problem

This branch added a second addon-registry implementation, `ociRegistry`
(`pkg/addon/oci_registry.go`), alongside the existing `versionedRegistry`
(`pkg/addon/versioned_registry.go`). Both satisfy the same `VersionedRegistry`
interface, both decode a Helm chart archive into a `WholeAddonPackage`, and both
are reached through a different constructor. The result is a Helm-versus-OCI
branch at every call site that reads a chart-backed registry.

The duplication inside the registry implementations is modest (about seventy
lines: `GetAddonUIData`, `GetAddonInstallPackage`, `GetDetailedAddon`, and the
archive-to-package-plus-stamp sequence). The larger cost is the eleven call
sites that have to know which of the two they are holding:

| Site | Branch |
|---|---|
| `pkg/addon/helper.go:301` | `IsVersionRegistry` / `IsOCIRegistry` switch |
| `pkg/addon/helper.go:386` | two sequential `if` blocks |
| `pkg/addon/cache.go:383` | `isVersionCapableRegistry` exists only to paper over the split |
| `pkg/addon/addon.go:980` | `IsOCIRegistry(*h.r) \|\| IsVersionRegistry(*h.r)` |
| `pkg/addon/addon.go:1721` | HTTP-Helm only; OCI silently returns `""` |
| `pkg/addon/utils.go:190` | HTTP-Helm only; OCI falls through to `BuildReader` |
| `pkg/addon/source.go:480` | `isVersionCapableRegistry` |
| `pkg/addon/push.go:92` | `IsOCIRegistry` |
| `references/cli/addon.go:1057` | `!IsVersionRegistry && !IsOCIRegistry` |
| `references/cli/addon-registry.go:235` | `registry.OCI` display case |
| `references/cli/addon-registry.go:273` | `registry.OCI` display case |

Two of these are defects today. `utils.go:190` checks only `IsVersionRegistry`,
so disabling an addon that was installed from an OCI registry takes the
`AsyncReader` path and fails in `source.go:416` with "registry don't have enough
info to build a reader". `addon.go:1721` never suggests a compatible version for
an OCI registry.

The split is also visible in the stored configuration. `Registry` carries both a
`Helm` block and an `OCI` block, and which one wins depends on the operation:
reads prefer Helm, push prefers OCI, and the credential Secret lifecycle follows
OCI because `HelmSource` is not a `TokenSource`.

## Why now, and why this is cheap

`pkg/addon/oci_registry.go` was introduced in commit `1c7ff1b28` and exists only
on `feat/addon-component` and a branch derived from it. It is absent from
`gwoss/master`. No released binary writes `{"oci": ...}` into the
`vela-addon-registry` ConfigMap, and no user has such a record.

That removes the entire migration problem. There is no deprecation window, no
mixed-block precedence matrix, no `vela addon registry migrate` command, and no
compatibility adapter to maintain. The OCI configuration surface can be replaced
outright because nothing has depended on it yet.

## Constraint

The HTTP Helm repository path is released and must not change behavior. This
refactor rewrites only code added on this branch, plus the minimum guards needed
where a Helm block can now hold an `oci://` URL. Concretely:

- `chooseVersion`, prerelease skipping, `v`-prefix tolerance, relative chart-URL
  joining, the multi-URL download retry loop, `common.HTTPOption` handling, and
  the `LoadSystemRequirements(annotations)` overwrite (including overwrite with
  `nil`) all keep their current semantics.
- `HelmSource.Password` for an `http(s)://` registry keeps going to the
  ConfigMap exactly as it does today. Secret-backing applies only to `oci://`.
- `BuildVersionedRegistry(name, url, opts)` keeps its signature and its
  HTTP-only meaning.
- The existing HTTP suites (`versioned_registry_test.go`,
  `versioned_registry_suite_test.go`, `push_helm_repo_test.go`) are the guard:
  they must pass unmodified, before and after.

## Design

### Configuration

`Registry.OCI` and `OCIAddonSource` are deleted. An OCI registry is a Helm
registry whose URL carries the `oci://` scheme.

```go
type HelmSource struct {
    URL             string `json:"url,omitempty" validate:"required"`
    InsecureSkipTLS bool   `json:"insecureSkipTLS,omitempty"`
    Username        string `json:"username,omitempty"`
    // Password authenticates an http(s):// Helm repository. Unused for oci://.
    Password        string `json:"password,omitempty"`
    // Token authenticates an oci:// registry. For ECR, Username is "AWS" and
    // Token is the output of `aws ecr get-login-password`. Unused for http(s)://.
    Token          string `json:"token,omitempty"`
    // TokenSecretRef names the Secret holding Token. oci:// only.
    TokenSecretRef string `json:"tokenSecretRef,omitempty"`
}
```

The OCI credential fields keep the names and JSON keys they have on
`OCIAddonSource`, so the move is a straight field copy and the term a user types
into the ConfigMap does not change. `HelmSource` implements `TokenSource` over
`Token` and `TokenSecretRef`, which means `migrateInlineTokenToSecret` and
`loadTokenFromSecret` work unchanged on Secret data key `token`, the same key
Git, Gitee and GitLab registry Secrets already use.

Where the credential lives, by scheme:

| Concern | `http(s)://` | `oci://` |
|---|---|---|
| Go field | `HelmSource.Password` | `HelmSource.Token` |
| ConfigMap JSON | `password` | `token`, then `tokenSecretRef` once moved |
| Secret data key | none, the value stays inline | `token`, the same key Git, Gitee and GitLab already use |
| `Registry.GetTokenSource()` | `nil`, unchanged from today | returns the Helm source |
| `createOrUpdateTokenSecret` | never reached | moves `Token` into `addon-registry-<name>` |
| CLI flags | `--username`, `--password`, `--password-stdin` | same flags, value lands in `Token` |
| Read by the backend | `credential()` returns `Password` | `credential()` returns `Token` |
| Rejected as a misconfiguration | `token` set on this URL | `password` set on this URL |

Two credential fields on one struct create an invariant to police: `token` set
on an `http(s)://` URL, or `password` set on an `oci://` URL, is a
misconfiguration that would otherwise surface as an opaque 401. Both
`NewVersionedRegistry` and the CLI parse reject that pair. The backends read the
credential through one helper rather than reaching for a field directly:

```go
func (h *HelmSource) credential() (username, secret string) {
    if IsOCIURL(h.URL) {
        return h.Username, h.Token
    }
    return h.Username, h.Password
}
```

`Registry.GetTokenSource` returns the Helm source only when the URL is `oci://`:

```go
func (r *Registry) GetTokenSource() TokenSource {
    // ... Git, Gitee, Gitlab unchanged ...
    if r.Helm != nil && IsOCIURL(r.Helm.URL) {
        return r.Helm
    }
    return nil
}
```

An `https://` Helm registry therefore returns `nil` exactly as it does today and
never reaches `createOrUpdateTokenSecret`, so its `Password` keeps going to the
ConfigMap.

URL classification uses the scheme, not a string prefix:

```go
func IsOCIURL(rawURL string) bool {
    u, err := url.Parse(rawURL)
    if err != nil {
        return false
    }
    return strings.EqualFold(u.Scheme, registry.OCIScheme) // helm's "oci"
}
```

### Registry façade and transport backends

One `VersionedRegistry` implementation, two transports behind a seam.

```go
type chartBackend interface {
    // ListUIData is the registry-wide listing: index entries for HTTP,
    // portable catalog (or /v2/_catalog fallback) for OCI.
    ListUIData(ctx context.Context) ([]*UIData, error)
    // Versions enumerates an addon's versions, newest first.
    Versions(ctx context.Context, addonName string) ([]*repo.ChartVersion, error)
    // Resolve selects a version and returns its decoded chart files.
    Resolve(ctx context.Context, addonName, version string) (*resolvedChart, error)
    // supportsVersionRequirements reports whether Versions carries the
    // annotations that SystemRequirements are read from.
    supportsVersionRequirements() bool
}

type resolvedChart struct {
    files             []*loader.BufferedFile
    version           string
    availableVersions []string
    // requirements is applied to the package only when requirementsSet is
    // true, so "the index says nil" stays distinct from "the transport has
    // no opinion".
    requirements    *SystemRequirements
    requirementsSet bool
}

type helmRegistry struct {
    name    string
    backend chartBackend
}
```

`Resolve` returns decoded `BufferedFile`s rather than raw bytes so the HTTP
backend keeps its current behavior of walking `addonVersion.URLs` and continuing
past a URL whose download *or* archive load fails. Moving only the download into
the backend would have changed that loop.

The façade owns everything the two transports genuinely share:

```go
func (r *helmRegistry) loadAddon(ctx context.Context, name, version string) (*WholeAddonPackage, error) {
    resolved, err := r.backend.Resolve(ctx, name, version)
    if err != nil {
        return nil, err
    }
    pkg, err := loadAddonPackage(name, resolved.files)
    if err != nil {
        return nil, err
    }
    pkg.RegistryName = r.name
    pkg.AvailableVersions = resolved.availableVersions
    if resolved.requirementsSet {
        pkg.Meta.SystemRequirements = resolved.requirements
    }
    return pkg, nil
}
```

`GetAddonUIData`, `GetAddonInstallPackage`, and `GetDetailedAddon` become thin
projections over `loadAddon` and exist once.

Construction is checked and scheme-driven:

```go
func NewVersionedRegistry(name, repoURL string, opts *common.HTTPOption) (VersionedRegistry, error)
```

`http`/`https` selects `httpHelmBackend`; `oci` selects `ociHelmBackend`; any
other scheme is a construction error rather than a runtime surprise.
`BuildVersionedRegistry` stays as the HTTP-only constructor it is today, so its
callers and its signature do not move. `ToVersionedRegistry(Registry)` becomes a
single call into `NewVersionedRegistry` using `registry.Helm`.

### Preserving per-transport error classification

`ociRegistry.loadAddon` wraps any error that is not already `ErrNotExist` or
`ErrFetch` into `ErrFetch`, which is what lets `installDependency` fall through
to the next registry via `isSkippableRegistryError`. The HTTP path deliberately
does not do this. A "specified version not exist" error stays unwrapped there.

To keep both behaviors exactly, the OCI backend implements an optional
classifier that the façade applies to its own errors:

```go
type errorClassifier interface {
    classify(error) error
}
```

`ociHelmBackend` implements it; `httpHelmBackend` does not, so the HTTP path is
byte-for-byte unchanged.

### The false-compatible-version trap

Folding OCI into the Helm block makes `IsVersionRegistry` (`r.Helm != nil`) true
for OCI registries. `addon.go:1721` would then start calling
`GetAddonAvailableVersion` on an OCI registry. OCI `repo.ChartVersion` values are
synthesized from tags and carry no annotations, so
`LoadSystemRequirements(nil)` returns `nil`, `checkAddonVersionMeetRequired(nil)`
returns `nil`, and the first tag would be reported as "compatible" whether or not
it is.

`supportsVersionRequirements()` exists for this. `getAddonVersionMeetSystemRequirement`
returns `""` for a backend that answers false, which is the same non-answer OCI
gives today rather than a wrong answer. This is a trap to avoid, not a bug to fix.

### Push

`pushToOCI`, `pushOCI`, `updateOCIAddonCatalog`, and the catalog helpers take
`*HelmSource` in place of the deleted `*OCIAddonSource`; they need only URL,
username, and password. `PushCmd.ociPushFn`'s signature changes to match.

Routing:

- `RepoName` starting with `oci://` goes direct to OCI (unchanged).
- A configured registry routes to OCI when `reg.Helm != nil && IsOCIURL(reg.Helm.URL)`,
  replacing the `IsOCIRegistry(reg)` check at `push.go:92`.
- `GetHelmRepo` (`push.go:328`) gains an `IsOCIURL` guard next to its existing
  `reg.Helm == nil` skip, so an OCI record can never be handed to the ChartMuseum
  client. HTTP repositories take the same path as before.

### CLI

`--type oci` stays as the spelling (the branch's own tests and examples use it)
but now writes a Helm block, validating that the endpoint scheme really is
`oci://`. `--type helm` with an `oci://` endpoint is accepted and produces the
identical record. The both-or-neither username/password check moves with it, and
`--insecureSkipTLS` is rejected for `oci://` rather than silently ignored.

`registry add` currently validates a Helm registry by calling `ListAddon()`. For
an `oci://` endpoint that reaches catalog discovery, and a genuinely fresh
registry with no catalog yet answers `ErrOCICatalogAbsent`. Add tolerates that
one error for `oci://` while still failing on auth and connectivity errors. The
`http(s)://` validation path is unchanged.

`registry list` and `registry get` derive the displayed type from the URL
(`oci` when `IsOCIURL`, otherwise `helm`), and their `registry.OCI` cases are
deleted.

### File layout

| File | Change |
|---|---|
| `pkg/addon/versioned_registry.go` | `VersionedRegistry`, `helmRegistry`, `chartBackend`, `resolvedChart`, `NewVersionedRegistry`, `ToVersionedRegistry`, `BuildVersionedRegistry`, `loadAddonPackage`, `chooseVersion`, `LoadSystemRequirements` |
| `pkg/addon/backend_http.go` | new: `httpHelmBackend`, extracted verbatim from `versionedRegistry` |
| `pkg/addon/backend_oci.go` | renamed from `oci_registry.go`: `ociHelmBackend` plus the pull/tags/catalog transport helpers, which are unchanged |
| `pkg/addon/oci_catalog.go` | logic unchanged; takes `*HelmSource` |
| `pkg/addon/source.go` | `OCIAddonSource` deleted; `HelmSource` gains `Token`, `TokenSecretRef` and the `TokenSource` methods; `IsOCIURL` and `credential()` added |
| `pkg/addon/registry.go` | `GetTokenSource` OCI case replaced by the `oci://`-guarded Helm case |
| `pkg/addon/cache.go` | `isVersionCapableRegistry` deleted; call sites use `IsVersionRegistry` |
| `pkg/addon/helper.go` | both switches collapse to `ToVersionedRegistry` |
| `pkg/addon/utils.go` | `IsOCIRegistry` deleted; `findLegacyAddonDefs` fixed for free |
| `pkg/addon/addon.go` | `loadInstallPackage` predicate simplified; `getAddonVersionMeetSystemRequirement` guarded by `supportsVersionRequirements` |
| `pkg/addon/push.go` | OCI routing by URL; `GetHelmRepo` skips `oci://` |
| `references/cli/addon-registry.go` | `--type oci` writes a Helm block; display type from URL |
| `references/cli/addon.go` | single `IsVersionRegistry` predicate |

## Deletions

`ociRegistry` and its five `VersionedRegistry` methods, `BuildOCIRegistry`,
`OCIAddonSource` and its five methods, `Registry.OCI`, `IsOCIRegistry`,
`isVersionCapableRegistry`, and the Helm-versus-OCI switches at the eleven call
sites above.

Nothing OCI-specific in transport is deleted: the registry-client pull and
login, strict-semver tag listing, `/v2/_catalog` enumeration with its
same-host pagination check, the portable catalog encode/decode and its
optimistic publish loop, `ErrOCICatalogAbsent`, and the `NAME_UNKNOWN`
absence test all move into the backend intact. An HTTP Helm repository gets
these capabilities from `index.yaml`; an OCI registry has no equivalent, so
this is compensation, not duplication.

## Testing

Order matters: the HTTP suites are the guard rail and run first.

1. Baseline. Run `versioned_registry_test.go`, `versioned_registry_suite_test.go`,
   `push_helm_repo_test.go`, `cache_test.go`, and `registry_test.go` before any
   edit and record the result. These files are not modified by the refactor;
   if any of them needs a change, the HTTP path moved and the change is wrong.
2. `IsOCIURL` table test: `oci://`, `OCI://`, `https://`, `http://`, `cm://`,
   empty, and a malformed URL.
3. `NewVersionedRegistry` factory test: scheme selects the backend; an
   unsupported scheme returns a construction error.
4. Retarget `oci_registry_test.go` to `backend_oci_test.go`, keeping the
   `pullFn` / `tagsFn` / `catalogFn` / `catalogIndexFn` seams on
   `ociHelmBackend`: tag filtering, exact and latest pull, ECR-style catalog
   absence, refusal of a foreign pagination host, plain HTTP, and auth failure.
5. `registry_test.go` additions: a Helm block with an `oci://` URL moves `token`
   into the Secret and clears the inline field; a Helm block with an `https://`
   URL creates no Secret and keeps `password` in the ConfigMap as today;
   deleting an `oci://` registry deletes its Secret. Also assert the rejected
   pairs: `token` set on an `http(s)://` URL, and `password` set on an `oci://`
   URL.
6. Fixture swap in `cache_oci_test.go`, `cache_getuidata_test.go`,
   `addon_coverage_test.go`, `helper_registry_lookup_test.go`, and
   `addon_loadinstall_test.go`: `Registry{OCI: ...}` becomes
   `Registry{Helm: &HelmSource{URL: "oci://...", Token: "..."}}`.
7. `push_oci_test.go` and `push_pushoci_test.go`: seam signature change, plus a
   new test that `GetHelmRepo` skips an `oci://` registry.
8. `references/cli/addon_test.go`: `--type oci` writes a Helm block;
   `--type helm` with `oci://` produces the same record; `--type oci` with an
   `https://` endpoint is rejected; `list` and `get` display `oci`; `add`
   tolerates `ErrOCICatalogAbsent` but not an auth failure.
9. Regression test: `getAddonVersionMeetSystemRequirement` returns `""` for an
   OCI registry rather than the first tag.
10. Contract tests: `pkg/addon/service`, the CueX addon provider, and the
    addon compatibility webhook must pass unchanged, proving the addon-component
    contract did not move.
11. Full run: `go test ./pkg/addon/... ./references/cli/... ./pkg/webhook/...`
    with `CGO_ENABLED=0` in this container.

## Risks

**A Helm block can now mean OCI.** Every `.Helm` reader has to tolerate an
`oci://` URL. There are eleven in non-test code and all are listed in the file
table above; the audit is `grep -rn --include='*.go' '\.Helm\b' pkg/ references/`.
The dangerous ones are `push.go:328` (would hand an `oci://` URL to ChartMuseum)
and `addon.go:1722` (would build an HTTP registry for an OCI URL).

**Silent-versus-logged failure in `FindAddonPackagesDetailFromRegistry`.** The
HTTP branch swallows a per-addon error with a bare `continue`; the OCI branch
logs a warning first. Collapsing them means the HTTP path gains a log line. That
is output-only, but it is a change to a released path and should be called out
in the PR.

**`AvailableVersions` on a pinned resolve.** HTTP returns the full index list
even when a version is pinned; OCI returns nothing, because a pinned request
never lists tags. Both behaviors are preserved as-is. Aligning them is a
separate decision.

**Prerelease and `v`-prefix semantics still differ.** HTTP `chooseVersion` skips
prereleases when no version is given and ignores a leading `v`; OCI takes the
head of Helm's strict-semver tag sort, which drops a tag like `v0.0.1` entirely.
This refactor preserves both. Normalizing them is out of scope.

**Catalog safety.** The absence classification must stay conservative: only
`NAME_UNKNOWN`, and only `404`/`405`/`501` from `/v2/_catalog`, count as
absence. A generic error, an auth failure, or a timeout must not be read as an
empty catalog, because the publish path rebuilds the catalog from what it read.

## Decisions

Three questions were open when this design was drafted. All three are settled.

`--type oci` stays as a CLI spelling. Both `--type oci --endpoint oci://...` and
`--type helm --endpoint oci://...` are accepted, write the identical Helm block,
and validate the scheme. The examples at `addon-registry.go:81-82` and the four
cases in `references/cli/addon_test.go:569-604` keep working unchanged.

The merged per-addon failure path in `FindAddonPackagesDetailFromRegistry` logs
for both transports. `helper.go:301` currently swallows an HTTP error with a bare
`continue`; it gets the same `klog.Warningf` the OCI branch already has. This is
the only place the released HTTP path changes at all, and it changes only what
reaches the log.

`AvailableVersions` on a pinned resolve keeps its current per-transport behavior.
HTTP returns the full index list, OCI returns none. Both are pinned by tests and
left alone, so aligning them stays a separate, reviewable change.

## Out of scope

Git, Gitee, GitLab, OSS, and local registry readers. The addon package format.
The addon component CUE contract and its render service. The chart component's
separate `repoType: oci` in `pkg/utils/helm`. Any change to HTTP Helm
credential storage. Any alignment of version-selection semantics between the two
transports.
