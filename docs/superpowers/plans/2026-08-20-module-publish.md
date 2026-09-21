# `vela module publish` (ECR/OCI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a validated module tree to ECR (or any OCI registry) as a Helm-chart artifact tagged from `_module.cue version`, refusing to overwrite a published version.

**Architecture:** Three layers. `pkg/module/publish.go` packages a parsed module into a chart archive plus annotations, with no network and no mutation of the source tree. `pkg/addon/oci_push.go` pushes that archive and reads tags, mirroring the existing exported `PullOCIChartFiles`. `references/cli/module-publish.go` parses arguments, resolves the target registry, gates on the parser, and turns registry failures into actionable messages.

**Tech Stack:** Go 1.23, cobra, helm.sh/helm/v3 v3.14.4 (`chartutil`, `chart/loader`, `registry`), github.com/google/go-containerregistry v0.18.0 (in-process registry for the live test), stretchr/testify.

Design: `docs/superpowers/specs/2026-08-20-module-publish-design.md`. Spec: `/workspaces/Open_Source/specs/oss-kubevela/module-registry/gwcp-106685-module-publish/`.

## Global Constraints

- Run every Go command with `CGO_ENABLED=0` in this devcontainer; without it the toolchain fails with `cannot find 'ld'`.
- No new module dependencies. Everything used here is already in `go.mod` (helm v3.14.4, go-containerregistry v0.18.0, testify).
- No `aws-sdk-go`. ECR is reached as a plain OCI registry, authenticated through Helm's docker-config fallback.
- The chart name is `Module.Name` from `_module.cue`, never the directory argument. The tag is `Module.Version`, or `--version` when given, and must be strict semver. Chart version and tag are always the same string, because Helm's `Push` runs in strict mode and requires `ref` to end in `/<chartName>:<chartVersion>`.
- Publish never writes into the module source directory, on success or failure.
- Publish never writes the `kubevela-addon-catalog` artifact.
- Annotation keys, exactly: `modules.oam.dev/module`, `modules.oam.dev/lines`, `modules.oam.dev/enabled-lines`.
- Every new exported identifier gets a doc comment starting with its own name (the repo runs `revive`).
- No comments inside function bodies unless they explain a non-obvious constraint.
- Commit after each task, one commit per task.

---

### Task 1: Package a module tree into a chart archive

**Files:**
- Create: `pkg/module/publish.go`
- Create: `pkg/module/publish_test.go`

**Interfaces:**
- Consumes: `ParseModuleDir(dir string) (*Module, error)` and `validateModuleVersion(version, path string) error`, both already in package `module` (`parse.go:87`, `validate.go:44`). `Module` and `Line` are in `module.go`.
- Produces:
  - `type Artifact struct { Module *Module; Tag string; Annotations map[string]string; Archive []byte }`
  - `func PackageModule(dir, versionOverride string) (*Artifact, error)`
  - `const AnnotationModule = "modules.oam.dev/module"`, `AnnotationLines`, `AnnotationEnabledLines`

- [ ] **Step 1: Write the failing tests**

Create `pkg/module/publish_test.go`:

```go
/*
Copyright 2021 The KubeVela Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package module

import (
	"bytes"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"helm.sh/helm/v3/pkg/chart/loader"
)

// archiveFS turns a packaged chart archive back into the fs.FS a fetch would
// see: the files under the chart's top-level directory, with that prefix
// stripped, exactly as pkg/module/service/fetch.go does after a pull.
func archiveFS(t *testing.T, archive []byte, chartName string) fs.FS {
	t.Helper()
	files, err := loader.LoadArchiveFiles(bytes.NewReader(archive))
	require.NoError(t, err)
	prefix := chartName + "/"
	out := fstestMapFS{}
	for _, f := range files {
		rel := strings.TrimPrefix(f.Name, prefix)
		if rel == f.Name {
			continue
		}
		out[rel] = f.Data
	}
	require.NotEmpty(t, out, "archive held no files under %q", prefix)
	return out
}

func TestPackageModuleRoundTrip(t *testing.T) {
	for _, dir := range []string{"testdata/modules/s3", "testdata/modules/minimal"} {
		t.Run(dir, func(t *testing.T) {
			source, err := ParseModuleDir(dir)
			require.NoError(t, err)

			art, err := PackageModule(dir, "")
			require.NoError(t, err)
			require.Equal(t, source.Version, art.Tag)

			pulled, err := ParseModule(archiveFS(t, art.Archive, source.Name))
			require.NoError(t, err)
			require.Equal(t, source, pulled)
		})
	}
}

func TestPackageModuleArchiveContents(t *testing.T) {
	art, err := PackageModule("testdata/modules/s3", "")
	require.NoError(t, err)

	files, err := loader.LoadArchiveFiles(bytes.NewReader(art.Archive))
	require.NoError(t, err)
	names := map[string]bool{}
	for _, f := range files {
		names[f.Name] = true
	}
	for _, want := range []string{
		"s3/Chart.yaml",
		"s3/_module.cue",
		"s3/auxiliary/xrd.yaml",
		"s3/v1/_version.cue",
		"s3/v1/auxiliary/composition.yaml",
		"s3/v1/definitions/bucket.cue",
	} {
		require.True(t, names[want], "archive is missing %s, has %v", want, names)
	}
}

func TestPackageModuleAnnotations(t *testing.T) {
	dir := writeModuleTree(t, map[string]string{
		"_module.cue":                 "module:  \"two\"\nversion: \"2.3.4\"\n",
		"v1/_version.cue":             "apiVersion: \"v1\"\n",
		"v1/definitions/one.yaml":     "apiVersion: core.oam.dev/v1beta1\nkind: ComponentDefinition\nmetadata:\n  name: one\n",
		"v2/_version.cue":             "apiVersion: \"v2\"\nenabled: false\n",
		"v2/definitions/two.yaml":     "apiVersion: core.oam.dev/v1beta1\nkind: ComponentDefinition\nmetadata:\n  name: two\n",
	})

	art, err := PackageModule(dir, "")
	require.NoError(t, err)
	require.Equal(t, map[string]string{
		AnnotationModule:       "two",
		AnnotationLines:        "v1,v2",
		AnnotationEnabledLines: "v1",
	}, art.Annotations)
}

func TestPackageModuleVersionOverride(t *testing.T) {
	art, err := PackageModule("testdata/modules/s3", "1.1.0-rc1")
	require.NoError(t, err)
	require.Equal(t, "1.1.0-rc1", art.Tag)
	require.Equal(t, "1.0.0", art.Module.Version)

	_, err = PackageModule("testdata/modules/s3", "latest")
	require.ErrorContains(t, err, "not a valid semver")
}

func TestPackageModuleInvalidTreeIsRejected(t *testing.T) {
	dir := writeModuleTree(t, map[string]string{
		"_module.cue": "module:  \"bad\"\nversion: \"nope\"\n",
	})
	_, err := PackageModule(dir, "")
	require.ErrorContains(t, err, "not a valid semver")
}

func TestPackageModuleLeavesSourceTreeUntouched(t *testing.T) {
	dir := writeModuleTree(t, map[string]string{
		"_module.cue":             "module:  \"keep\"\nversion: \"1.0.0\"\n",
		"v1/_version.cue":         "apiVersion: \"v1\"\n",
		"v1/definitions/d.yaml":   "apiVersion: core.oam.dev/v1beta1\nkind: ComponentDefinition\nmetadata:\n  name: d\n",
		".helmignore":             "v1/\n",
	})
	before := treeSnapshot(t, dir)

	art, err := PackageModule(dir, "")
	require.NoError(t, err)
	require.Equal(t, before, treeSnapshot(t, dir))

	files, err := loader.LoadArchiveFiles(bytes.NewReader(art.Archive))
	require.NoError(t, err)
	for _, f := range files {
		require.NotEqual(t, "keep/.helmignore", f.Name)
	}
	require.FileExists(t, filepath.Join(dir, ".helmignore"))

	pulled, err := ParseModule(archiveFS(t, art.Archive, "keep"))
	require.NoError(t, err)
	require.Contains(t, pulled.Lines, "v1")
}

// writeModuleTree writes files (keyed by slash-separated relative path) into a
// fresh temp directory and returns it.
func writeModuleTree(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	for rel, content := range files {
		p := filepath.Join(dir, filepath.FromSlash(rel))
		require.NoError(t, os.MkdirAll(filepath.Dir(p), 0o750))
		require.NoError(t, os.WriteFile(p, []byte(content), 0o600))
	}
	return dir
}

// treeSnapshot maps every file path under dir to its contents, so a test can
// assert the directory is byte-identical before and after an operation.
func treeSnapshot(t *testing.T, dir string) map[string]string {
	t.Helper()
	out := map[string]string{}
	require.NoError(t, filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		data, readErr := os.ReadFile(filepath.Clean(p))
		if readErr != nil {
			return readErr
		}
		rel, relErr := filepath.Rel(dir, p)
		if relErr != nil {
			return relErr
		}
		out[filepath.ToSlash(rel)] = string(data)
		return nil
	}))
	return out
}

// fstestMapFS is a tiny fs.FS over an in-memory file map, enough for
// ParseModule (ReadFile plus ReadDir).
type fstestMapFS map[string][]byte
```

Then implement `fstestMapFS` by delegating to `testing/fstest`:

```go
func (m fstestMapFS) Open(name string) (fs.File, error) { return m.mapFS().Open(name) }

func (m fstestMapFS) ReadFile(name string) ([]byte, error) { return m.mapFS().ReadFile(name) }

func (m fstestMapFS) ReadDir(name string) ([]fs.DirEntry, error) { return m.mapFS().ReadDir(name) }

func (m fstestMapFS) mapFS() fstest.MapFS {
	out := fstest.MapFS{}
	for p, data := range m {
		out[p] = &fstest.MapFile{Data: data}
	}
	return out
}
```

Add `"testing/fstest"` to the import block.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CGO_ENABLED=0 go test ./pkg/module/ -run 'TestPackageModule' -count=1`
Expected: FAIL to build, `undefined: PackageModule`.

- [ ] **Step 3: Write the implementation**

Create `pkg/module/publish.go` with the Apache header used by every file in the package, then:

```go
package module

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"helm.sh/helm/v3/pkg/chart"
	"helm.sh/helm/v3/pkg/chart/loader"
	"helm.sh/helm/v3/pkg/chartutil"
)

const (
	// AnnotationModule is the OCI annotation recording the published module's
	// name, so a registry listing identifies the module without pulling it.
	AnnotationModule = "modules.oam.dev/module"

	// AnnotationLines is the OCI annotation recording every API line in the
	// published artifact, comma-separated and sorted.
	AnnotationLines = "modules.oam.dev/lines"

	// AnnotationEnabledLines is the OCI annotation recording the subset of
	// lines their author left enabled, which is what the render service
	// installs. It is absent when no line is enabled.
	AnnotationEnabledLines = "modules.oam.dev/enabled-lines"

	// chartTypeLibrary marks the artifact a Helm library chart so nobody can
	// helm install a module by accident, matching what addon packaging does.
	chartTypeLibrary = "library"
)

// Artifact is a module packaged for publication: the parsed module, the tag it
// publishes under, the OCI annotations to stamp, and the Helm chart archive
// carrying the module tree.
type Artifact struct {
	Module      *Module
	Tag         string
	Annotations map[string]string
	Archive     []byte
}

// PackageModule parses the module tree at dir and packages it as a Helm chart
// archive named after the module and tagged from its version, or from
// versionOverride when that is set. The chart name must be the module's own
// name: the fetch strips a <moduleName>/ prefix from the files it pulls back,
// so an archive built under any other name reads as an empty module.
//
// dir is read only. The generated Chart.yaml is written into a temporary copy
// of the tree, so publishing leaves the author's source directory untouched
// whether it succeeds or fails.
func PackageModule(dir, versionOverride string) (*Artifact, error) {
	mod, err := ParseModuleDir(dir)
	if err != nil {
		return nil, err
	}

	tag := mod.Version
	if versionOverride != "" {
		if err := validateModuleVersion(versionOverride, "--version"); err != nil {
			return nil, err
		}
		tag = versionOverride
	}

	workdir, err := os.MkdirTemp("", "vela-module-publish-")
	if err != nil {
		return nil, fmt.Errorf("package module %q: create work directory: %w", mod.Name, err)
	}
	defer func() {
		_ = os.RemoveAll(workdir)
	}()

	treeDir := filepath.Join(workdir, "tree")
	if err := copyModuleTree(dir, treeDir); err != nil {
		return nil, fmt.Errorf("package module %q: %w", mod.Name, err)
	}

	annotations := moduleAnnotations(mod)
	meta := &chart.Metadata{
		APIVersion:  chart.APIVersionV2,
		Name:        mod.Name,
		Version:     tag,
		AppVersion:  mod.Version,
		Type:        chartTypeLibrary,
		Description: fmt.Sprintf("KubeVela module %s", mod.Name),
		Annotations: annotations,
	}
	if err := chartutil.SaveChartfile(filepath.Join(treeDir, chartutil.ChartfileName), meta); err != nil {
		return nil, fmt.Errorf("package module %q: write %s: %w", mod.Name, chartutil.ChartfileName, err)
	}

	ch, err := loader.LoadDir(treeDir)
	if err != nil {
		return nil, fmt.Errorf("package module %q: load chart: %w", mod.Name, err)
	}
	outDir := filepath.Join(workdir, "out")
	if err := os.Mkdir(outDir, 0o750); err != nil {
		return nil, fmt.Errorf("package module %q: create output directory: %w", mod.Name, err)
	}
	archivePath, err := chartutil.Save(ch, outDir)
	if err != nil {
		return nil, fmt.Errorf("package module %q: package chart: %w", mod.Name, err)
	}
	archive, err := os.ReadFile(filepath.Clean(archivePath))
	if err != nil {
		return nil, fmt.Errorf("package module %q: read archive: %w", mod.Name, err)
	}

	return &Artifact{Module: mod, Tag: tag, Annotations: annotations, Archive: archive}, nil
}

// moduleAnnotations builds the module, lines, and enabled-lines annotations,
// with line names sorted so a republished artifact is byte-stable.
func moduleAnnotations(mod *Module) map[string]string {
	lines := make([]string, 0, len(mod.Lines))
	enabled := make([]string, 0, len(mod.Lines))
	for name, line := range mod.Lines {
		lines = append(lines, name)
		if line.Enabled {
			enabled = append(enabled, name)
		}
	}
	sort.Strings(lines)
	sort.Strings(enabled)

	annotations := map[string]string{
		AnnotationModule: mod.Name,
		AnnotationLines:  strings.Join(lines, ","),
	}
	if len(enabled) > 0 {
		annotations[AnnotationEnabledLines] = strings.Join(enabled, ",")
	}
	return annotations
}

// copyModuleTree copies the module tree at src into dst.
//
// Three entries are deliberately dropped. A .helmignore would make Helm's
// directory loader skip the author's own files (loader applies ignore.Empty()
// only when the file is absent), silently shrinking the artifact. A .git
// directory is repository state, not module content. A Chart.yaml already in
// the tree is replaced by the generated one. Symlinks are rejected rather than
// followed, so packaging cannot reach outside the tree.
func copyModuleTree(src, dst string) error {
	return filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		if rel == "." {
			return os.MkdirAll(dst, 0o750)
		}
		base := d.Name()
		if d.IsDir() {
			if base == ".git" {
				return filepath.SkipDir
			}
			return os.MkdirAll(filepath.Join(dst, rel), 0o750)
		}
		if base == ".helmignore" || base == chartutil.ChartfileName {
			return nil
		}
		if d.Type()&fs.ModeSymlink != 0 {
			return fmt.Errorf("module tree contains a symlink at %s; publish requires plain files", rel)
		}
		data, err := os.ReadFile(filepath.Clean(p))
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(dst, rel), data, 0o600)
	})
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CGO_ENABLED=0 go test ./pkg/module/ -run 'TestPackageModule' -count=1 -v`
Expected: PASS, all subtests.

If `TestPackageModuleRoundTrip` fails on a missing file, print the archive's file names first: Helm's loader is the only thing between the tree and the archive, and the likely cause is a `templates/` or `charts/` directory in the fixture, which Helm reinterprets.

- [ ] **Step 5: Verify nothing else in the package broke**

Run: `CGO_ENABLED=0 go test ./pkg/module/... -count=1 && CGO_ENABLED=0 go vet ./pkg/module/... && gofmt -l pkg/module`
Expected: tests PASS, vet silent, `gofmt -l` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add pkg/module/publish.go pkg/module/publish_test.go
git commit -m "feat(module): package a module tree as a Helm chart artifact for publish"
```

---

### Task 2: OCI push, tag lookup, and loopback plain HTTP

**Files:**
- Create: `pkg/addon/oci_push.go`
- Create: `pkg/addon/oci_push_test.go`
- Modify: `pkg/addon/oci_registry.go` (`ociRegistryLocation` at :82, `newOCIClient` at :128)

**Interfaces:**
- Consumes: `ociRepoRef(url, addon string) (repoRef, host string)`, `newOCIClient(host, username, password string) (*registry.Client, error)`, `listOCITags(ctx, repoRef, host, username, password string) ([]string, error)`, and `Registry`/`OCIAddonSource` from `pkg/addon`.
- Produces:
  - `func PushOCIChart(ctx context.Context, reg Registry, name, version string, archive []byte) error`
  - `func OCIChartTagExists(ctx context.Context, reg Registry, name, tag string) (bool, error)`
  - `func OCIChartRef(reg Registry, name, tag string) (string, error)`
  - `func IsOCIRepositoryNotFound(err error) bool`
  - `func IsOCITagImmutable(err error) bool`

- [ ] **Step 1: Write the failing tests**

Create `pkg/addon/oci_push_test.go` with the standard Apache header, then:

```go
package addon

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestOCIChartRef(t *testing.T) {
	cases := []struct {
		name string
		url  string
		want string
	}{
		{name: "scheme and prefix", url: "oci://registry.example.com/modules", want: "registry.example.com/modules/s3:1.0.0"},
		{name: "no prefix", url: "oci://registry.example.com", want: "registry.example.com/s3:1.0.0"},
		{name: "bare ecr host", url: "123456789012.dkr.ecr.us-west-2.amazonaws.com/modules", want: "123456789012.dkr.ecr.us-west-2.amazonaws.com/modules/s3:1.0.0"},
		{name: "http scheme", url: "http://127.0.0.1:5000/modules", want: "127.0.0.1:5000/modules/s3:1.0.0"},
		{name: "trailing slash", url: "oci://registry.example.com/modules/", want: "registry.example.com/modules/s3:1.0.0"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ref, err := OCIChartRef(Registry{Name: "r", OCI: &OCIAddonSource{URL: tc.url}}, "s3", "1.0.0")
			require.NoError(t, err)
			require.Equal(t, tc.want, ref)
		})
	}
}

func TestOCIChartRefRejectsNonOCIRegistry(t *testing.T) {
	_, err := OCIChartRef(Registry{Name: "cat", Git: &GitAddonSource{URL: "https://github.com/org/repo"}}, "s3", "1.0.0")
	require.ErrorContains(t, err, "not an OCI registry")
}

func TestPushOCIChartRejectsNonOCIRegistry(t *testing.T) {
	err := PushOCIChart(context.Background(), Registry{Name: "cat", Git: &GitAddonSource{URL: "https://github.com/org/repo"}}, "s3", "1.0.0", []byte("x"))
	require.ErrorContains(t, err, "not an OCI registry")
}

func TestOCIChartTagExists(t *testing.T) {
	reg := Registry{Name: "r", OCI: &OCIAddonSource{URL: "oci://registry.example.com/modules"}}
	cases := []struct {
		name      string
		tags      []string
		tagsErr   error
		tag       string
		want      bool
		wantErr   string
	}{
		{name: "tag present", tags: []string{"1.1.0", "1.0.0"}, tag: "1.0.0", want: true},
		{name: "tag absent", tags: []string{"1.1.0"}, tag: "1.0.0", want: false},
		{name: "empty repository", tags: nil, tag: "1.0.0", want: false},
		{name: "repository missing", tagsErr: errors.New("unexpected status: 404 Not Found: NAME_UNKNOWN"), tag: "1.0.0", want: false},
		{name: "listing failed", tagsErr: errors.New("unauthorized"), tag: "1.0.0", wantErr: "unauthorized"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			restore := ociTagListerForTest(func(_ context.Context, _, _, _, _ string) ([]string, error) {
				return tc.tags, tc.tagsErr
			})
			defer restore()

			got, err := OCIChartTagExists(context.Background(), reg, "s3", tc.tag)
			if tc.wantErr != "" {
				require.ErrorContains(t, err, tc.wantErr)
				return
			}
			require.NoError(t, err)
			require.Equal(t, tc.want, got)
		})
	}
}

func TestIsOCIRepositoryNotFound(t *testing.T) {
	require.True(t, IsOCIRepositoryNotFound(errors.New("unexpected status: 404 Not Found: NAME_UNKNOWN")))
	require.True(t, IsOCIRepositoryNotFound(errors.New("RepositoryNotFoundException: The repository with name 'modules/s3' does not exist")))
	require.False(t, IsOCIRepositoryNotFound(errors.New("unauthorized: authentication required")))
}

func TestIsOCITagImmutable(t *testing.T) {
	require.True(t, IsOCITagImmutable(errors.New("ImageTagAlreadyExistsException: Tag 1.0.0 is immutable")))
	require.False(t, IsOCITagImmutable(errors.New("unauthorized: authentication required")))
}

func TestLoopbackRegistryHost(t *testing.T) {
	for _, host := range []string{"localhost", "localhost:5000", "127.0.0.1:5000", "[::1]:5000"} {
		require.True(t, isLoopbackRegistryHost(host), host)
	}
	for _, host := range []string{"registry.example.com", "123456789012.dkr.ecr.us-west-2.amazonaws.com"} {
		require.False(t, isLoopbackRegistryHost(host), host)
	}
}
```

Add the seam the tag test needs to `pkg/addon/oci_push.go` (production code, not the test file), so the tag lister can be swapped without a live registry:

```go
// ociTagListerForTest swaps the package tag lister and returns a function that
// restores it. It exists for tests in this package only.
func ociTagListerForTest(fn ociTagLister) func() {
	previous := chartTagLister
	chartTagLister = fn
	return func() { chartTagLister = previous }
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CGO_ENABLED=0 go test ./pkg/addon/ -run 'TestOCIChart|TestPushOCIChart|TestIsOCI|TestLoopback' -count=1`
Expected: FAIL to build, `undefined: OCIChartRef`.

- [ ] **Step 3: Write the implementation**

Create `pkg/addon/oci_push.go` with the Apache header, then:

```go
package addon

import (
	"context"
	"net"
	"strings"

	"github.com/pkg/errors"
)

// chartTagLister lists a repository's tags. It is a package variable so tests
// can substitute a fake; production always uses listOCITags.
var chartTagLister ociTagLister = listOCITags

// OCIChartRef returns the full OCI reference a module chart publishes to,
// "<host>[/<prefix>]/<name>:<tag>". It is exported so a caller can print the
// target before pushing.
func OCIChartRef(reg Registry, name, tag string) (string, error) {
	if reg.OCI == nil {
		return "", errors.Errorf("registry %q is not an OCI registry", reg.Name)
	}
	repoRef, _ := ociRepoRef(reg.OCI.URL, name)
	return repoRef + ":" + tag, nil
}

// PushOCIChart pushes a packaged Helm chart archive to reg as name:version.
// It is the push counterpart of PullOCIChartFiles and uses the same reference
// construction and the same authenticated Helm registry client, so a module
// published here is pulled by the module fetch unchanged.
func PushOCIChart(_ context.Context, reg Registry, name, version string, archive []byte) error {
	if reg.OCI == nil {
		return errors.Errorf("registry %q is not an OCI registry", reg.Name)
	}
	repoRef, host := ociRepoRef(reg.OCI.URL, name)
	client, err := newOCIClient(host, reg.OCI.Username, reg.OCI.Token)
	if err != nil {
		return err
	}
	ref := repoRef + ":" + version
	if _, err := client.Push(archive, ref); err != nil {
		return errors.Wrapf(err, "failed to push chart %s", ref)
	}
	return nil
}

// OCIChartTagExists reports whether tag is already published for name in reg.
// A repository that does not exist yet is reported as "no such tag" rather
// than an error: the first publish of a module is exactly that case.
func OCIChartTagExists(ctx context.Context, reg Registry, name, tag string) (bool, error) {
	if reg.OCI == nil {
		return false, errors.Errorf("registry %q is not an OCI registry", reg.Name)
	}
	repoRef, host := ociRepoRef(reg.OCI.URL, name)
	tags, err := chartTagLister(ctx, repoRef, host, reg.OCI.Username, reg.OCI.Token)
	if err != nil {
		if IsOCIRepositoryNotFound(err) {
			return false, nil
		}
		return false, errors.Wrapf(err, "failed to list tags for %s", repoRef)
	}
	for _, published := range tags {
		if published == tag {
			return true, nil
		}
	}
	return false, nil
}

// IsOCIRepositoryNotFound reports whether err is a registry's "this repository
// does not exist" answer. ECR reports RepositoryNotFoundException; the
// distribution API reports NAME_UNKNOWN.
func IsOCIRepositoryNotFound(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	for _, marker := range []string{"name_unknown", "name unknown", "repositorynotfoundexception", "repository not found"} {
		if strings.Contains(msg, marker) {
			return true
		}
	}
	return false
}

// IsOCITagImmutable reports whether err is the registry refusing to move an
// existing tag. On ECR this is the repository's IMMUTABLE tag mutability
// setting, which no client flag can override.
func IsOCITagImmutable(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "imagetagalreadyexistsexception") || strings.Contains(msg, "tag is immutable") || strings.Contains(msg, "repository is immutable")
}

// isLoopbackRegistryHost reports whether host addresses a registry on this
// machine, which is served over plain HTTP by every local registry and by the
// in-process test registry.
func isLoopbackRegistryHost(host string) bool {
	name := host
	if h, _, err := net.SplitHostPort(host); err == nil {
		name = h
	}
	name = strings.Trim(name, "[]")
	if name == "localhost" {
		return true
	}
	if ip := net.ParseIP(name); ip != nil {
		return ip.IsLoopback()
	}
	return false
}
```

Then make the two additive edits in `pkg/addon/oci_registry.go`.

`ociRegistryLocation` currently strips only `oci://`, so an `http://` URL parses as host `http:`. Replace its first line:

```go
func ociRegistryLocation(rawURL string) (host, prefix string) {
	trimmed := rawURL
	for _, scheme := range []string{"oci://", "https://", "http://"} {
		trimmed = strings.TrimPrefix(trimmed, scheme)
	}
	base := strings.Trim(trimmed, "/")
	host = base
	if i := strings.Index(base, "/"); i >= 0 {
		host = base[:i]
		prefix = strings.Trim(base[i+1:], "/")
	}
	return host, prefix
}
```

`newOCIClient` gains plain HTTP and insecure login for loopback hosts:

```go
func newOCIClient(host, username, password string) (*registry.Client, error) {
	var opts []registry.ClientOption
	plainHTTP := isLoopbackRegistryHost(host)
	if plainHTTP {
		opts = append(opts, registry.ClientOptPlainHTTP())
	}
	client, err := registry.NewClient(opts...)
	if err != nil {
		return nil, errors.Wrap(err, "failed to create OCI registry client")
	}
	if username != "" || password != "" {
		loginOpts := []registry.LoginOption{registry.LoginOptBasicAuth(username, password)}
		if plainHTTP {
			loginOpts = append(loginOpts, registry.LoginOptInsecure(true))
		}
		if err := client.Login(host, loginOpts...); err != nil {
			return nil, errors.Wrapf(err, "failed to login to OCI registry %s", host)
		}
	}
	return client, nil
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CGO_ENABLED=0 go test ./pkg/addon/ -run 'TestOCIChart|TestPushOCIChart|TestIsOCI|TestLoopback' -count=1 -v`
Expected: PASS.

- [ ] **Step 5: Verify the addon package still passes and record any pre-existing failures**

Run: `CGO_ENABLED=0 go test ./pkg/addon/... -count=1`

Several tests in this package need a live cluster or network and may already fail on this branch. Before treating any failure as yours, run the same command in a clean worktree at the branch point and compare:

```bash
git worktree add /tmp/vela-baseline HEAD~1
CGO_ENABLED=0 go test ./pkg/addon/... -count=1 2>&1 | tail -30   # in /tmp/vela-baseline
git worktree remove /tmp/vela-baseline --force
```

Report which failures are pre-existing rather than silently accepting them.

- [ ] **Step 6: Commit**

```bash
git add pkg/addon/oci_push.go pkg/addon/oci_push_test.go pkg/addon/oci_registry.go
git commit -m "feat(addon): add OCI chart push, tag lookup, and loopback plain HTTP"
```

---

### Task 3: The publish command

**Files:**
- Create: `references/cli/module-publish.go`
- Create: `references/cli/module-publish_test.go`
- Modify: `references/cli/module-registry.go:63` (mount publish on the `vela module` group)

**Interfaces:**
- Consumes: `pkgmodule.PackageModule`, `pkgmodule.Artifact`, `pkgmodule.ResolveRegistry`, `pkgmodule.NewStore`, `pkgmodule.SourceTypeName`, `pkgaddon.PushOCIChart`, `pkgaddon.OCIChartTagExists`, `pkgaddon.OCIChartRef`, `pkgaddon.IsOCIRepositoryNotFound`, `pkgaddon.IsOCITagImmutable`, `setRegistryPasswordFromStdin` (`references/cli/addon-registry.go:332`, keyed on the flag names `password` and `password-stdin`).
- Produces:
  - `func NewModulePublishCommand(c common.Args, ioStreams cmdutil.IOStreams) *cobra.Command`
  - `type modulePublishOptions struct { ... }` with `func (o *modulePublishOptions) run(ctx context.Context, cli client.Client, out io.Writer) error`

- [ ] **Step 1: Write the failing tests**

Create `references/cli/module-publish_test.go` with the Apache header, then:

```go
package cli

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	pkgaddon "github.com/oam-dev/kubevela/pkg/addon"
	pkgmodule "github.com/oam-dev/kubevela/pkg/module"
	"github.com/oam-dev/kubevela/pkg/utils/common"
)

const publishFixtureDir = "../../pkg/module/testdata/modules/s3"

// recordedPush captures what run() would have pushed.
type recordedPush struct {
	calls   int
	reg     pkgaddon.Registry
	name    string
	version string
	archive []byte
}

func (r *recordedPush) push(_ context.Context, reg pkgaddon.Registry, name, version string, archive []byte) error {
	r.calls++
	r.reg, r.name, r.version, r.archive = reg, name, version, archive
	return nil
}

// moduleRegistryClient returns a fake client holding the module registry
// ConfigMap with the given entries, in the format the store unmarshals:
// a map keyed by registry name.
func moduleRegistryClient(t *testing.T, entries map[string]pkgaddon.Registry) client.Client {
	t.Helper()
	data, err := json.Marshal(entries)
	require.NoError(t, err)
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: pkgmodule.ModuleRegistryConfigMap, Namespace: types.DefaultKubeVelaNS},
		Data:       map[string]string{"registries": string(data)},
	}
	return fake.NewClientBuilder().WithScheme(common.Scheme).WithObjects(cm).Build()
}

func TestModulePublishPushesArtifact(t *testing.T) {
	rec := &recordedPush{}
	o := &modulePublishOptions{
		dir:    publishFixtureDir,
		ociRef: "oci://registry.example.com/modules",
		push:   rec.push,
		tagExists: func(_ context.Context, _ pkgaddon.Registry, _, _ string) (bool, error) {
			return false, nil
		},
	}

	out := &bytes.Buffer{}
	require.NoError(t, o.run(context.Background(), nil, out))
	require.Equal(t, 1, rec.calls)
	require.Equal(t, "s3", rec.name)
	require.Equal(t, "1.0.0", rec.version)
	require.NotEmpty(t, rec.archive)
	require.Contains(t, out.String(), "registry.example.com/modules/s3:1.0.0")
}

func TestModulePublishDryRunPushesNothing(t *testing.T) {
	rec := &recordedPush{}
	o := &modulePublishOptions{
		dir:    publishFixtureDir,
		ociRef: "oci://registry.example.com/modules",
		dryRun: true,
		push:   rec.push,
		tagExists: func(_ context.Context, _ pkgaddon.Registry, _, _ string) (bool, error) {
			return false, errors.New("tagExists must not be called on a dry run")
		},
	}

	out := &bytes.Buffer{}
	require.NoError(t, o.run(context.Background(), nil, out))
	require.Zero(t, rec.calls)
	printed := out.String()
	require.Contains(t, printed, "registry.example.com/modules/s3:1.0.0")
	require.Contains(t, printed, "modules.oam.dev/lines")
}

func TestModulePublishFailsBeforePush(t *testing.T) {
	cases := []struct {
		name    string
		options func(rec *recordedPush) *modulePublishOptions
		wantErr string
	}{
		{
			name: "invalid module tree",
			options: func(rec *recordedPush) *modulePublishOptions {
				return &modulePublishOptions{dir: "testdata", ociRef: "oci://registry.example.com/modules", push: rec.push}
			},
			wantErr: "parse module",
		},
		{
			name: "git registry target",
			options: func(rec *recordedPush) *modulePublishOptions {
				return &modulePublishOptions{dir: publishFixtureDir, registry: "catalog", push: rec.push}
			},
			wantErr: "supports OCI/ECR only",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := &recordedPush{}
			cli := moduleRegistryClient(t, map[string]pkgaddon.Registry{
				"catalog": {Name: "catalog", Git: &pkgaddon.GitAddonSource{URL: "https://github.com/org/repo", Path: "module"}},
			})
			err := tc.options(rec).run(context.Background(), cli, &bytes.Buffer{})
			require.ErrorContains(t, err, tc.wantErr)
			require.Zero(t, rec.calls)
		})
	}
}

func TestModulePublishUsesResolvedRegistryCredentials(t *testing.T) {
	rec := &recordedPush{}
	cli := moduleRegistryClient(t, map[string]pkgaddon.Registry{
		"ecr": {Name: "ecr", OCI: &pkgaddon.OCIAddonSource{URL: "oci://123456789012.dkr.ecr.us-west-2.amazonaws.com/modules"}},
	})
	o := &modulePublishOptions{
		dir:  publishFixtureDir,
		push: rec.push,
		tagExists: func(_ context.Context, _ pkgaddon.Registry, _, _ string) (bool, error) {
			return false, nil
		},
	}

	require.NoError(t, o.run(context.Background(), cli, &bytes.Buffer{}))
	require.Equal(t, "ecr", rec.reg.Name)
	require.NotNil(t, rec.reg.OCI)
	require.Equal(t, "oci://123456789012.dkr.ecr.us-west-2.amazonaws.com/modules", rec.reg.OCI.URL)
}

func TestModulePublishVersionOverride(t *testing.T) {
	rec := &recordedPush{}
	o := &modulePublishOptions{
		dir:     publishFixtureDir,
		ociRef:  "oci://registry.example.com/modules",
		version: "1.1.0-rc1",
		push:    rec.push,
		tagExists: func(_ context.Context, _ pkgaddon.Registry, _, tag string) (bool, error) {
			require.Equal(t, "1.1.0-rc1", tag)
			return false, nil
		},
	}
	require.NoError(t, o.run(context.Background(), nil, &bytes.Buffer{}))
	require.Equal(t, "1.1.0-rc1", rec.version)
}

func TestModulePublishRequiresClusterForNamedRegistry(t *testing.T) {
	o := &modulePublishOptions{dir: publishFixtureDir, registry: "ecr"}
	err := o.run(context.Background(), nil, &bytes.Buffer{})
	require.ErrorContains(t, err, "cluster")
}

func TestModulePublishCommandFlagsAndMount(t *testing.T) {
	cmd := NewModulePublishCommand(common.Args{}, util.NewDefaultIOStreams())
	for _, flag := range []string{"registry", "version", "force", "dry-run", "username", "password", "password-stdin"} {
		require.NotNil(t, cmd.Flags().Lookup(flag), "missing flag %s", flag)
	}
	require.Error(t, cmd.Args(cmd, []string{}), "a module directory is required")
	require.NoError(t, cmd.Args(cmd, []string{"dir"}))
	require.NoError(t, cmd.Args(cmd, []string{"dir", "oci://registry.example.com/modules"}))
	require.Error(t, cmd.Args(cmd, []string{"dir", "ref", "extra"}))

	group := NewModuleCommand(common.Args{}, "1", util.NewDefaultIOStreams())
	names := map[string]bool{}
	for _, sub := range group.Commands() {
		names[sub.Name()] = true
	}
	require.True(t, names["publish"], "publish is not mounted on vela module")
}

func TestModulePublishRejectsRegistryFlagWithPositionalRef(t *testing.T) {
	o := &modulePublishOptions{dir: publishFixtureDir, registry: "ecr", ociRef: "oci://registry.example.com/modules"}
	err := o.run(context.Background(), nil, &bytes.Buffer{})
	require.ErrorContains(t, err, "cannot be combined")
}
```

Add the imports the helpers need: `encoding/json`, `github.com/oam-dev/kubevela/apis/types`, `github.com/oam-dev/kubevela/pkg/utils/util`, and drop `strings` if unused after writing the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestModulePublish' -count=1`
Expected: FAIL to build, `undefined: modulePublishOptions`.

- [ ] **Step 3: Write the implementation**

Create `references/cli/module-publish.go` with the Apache header, then:

```go
package cli

import (
	"context"
	"fmt"
	"io"
	"sort"

	"github.com/spf13/cobra"
	"sigs.k8s.io/controller-runtime/pkg/client"

	pkgaddon "github.com/oam-dev/kubevela/pkg/addon"
	pkgmodule "github.com/oam-dev/kubevela/pkg/module"
	"github.com/oam-dev/kubevela/pkg/utils/common"
	cmdutil "github.com/oam-dev/kubevela/pkg/utils/util"
)

const (
	modulePublishRegistryFlag = "registry"
	modulePublishVersionFlag  = "version"
	modulePublishForceFlag    = "force"
	modulePublishDryRunFlag   = "dry-run"
	modulePublishUsernameFlag = "username"
)

// modulePublishOptions holds the resolved inputs of vela module publish. The
// push and tagExists seams are wired to pkg/addon in production and replaced
// in tests, so no test needs a registry.
type modulePublishOptions struct {
	dir      string
	ociRef   string
	registry string
	version  string
	username string
	password string
	force    bool
	dryRun   bool

	push      func(ctx context.Context, reg pkgaddon.Registry, name, version string, archive []byte) error
	tagExists func(ctx context.Context, reg pkgaddon.Registry, name, tag string) (bool, error)
}

// NewModulePublishCommand returns the vela module publish command.
func NewModulePublishCommand(c common.Args, _ cmdutil.IOStreams) *cobra.Command {
	o := &modulePublishOptions{push: pkgaddon.PushOCIChart, tagExists: pkgaddon.OCIChartTagExists}
	cmd := &cobra.Command{
		Use:   "publish <dir> [oci-ref]",
		Short: "Publish a module to an OCI or ECR registry.",
		Long:  "Validate a module source tree and publish it as an OCI artifact tagged from its own version. A published version is immutable: change the module, bump version in _module.cue, publish again.",
		Example: `  Publish to the configured default registry:
	vela module publish ./modules/s3

  Publish to a named registry:
	vela module publish ./modules/s3 --registry ecr

  Publish straight to an ECR repository prefix:
	vela module publish ./modules/s3 123456789012.dkr.ecr.us-west-2.amazonaws.com/modules

  Check the target and the annotations without pushing:
	vela module publish ./modules/s3 --registry ecr --dry-run

  Republish a release candidate over itself while iterating:
	vela module publish ./modules/s3 --registry ecr --version 1.1.0-rc1 --force`,
		Args: cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := setRegistryPasswordFromStdin(cmd); err != nil {
				return err
			}
			o.dir = args[0]
			if len(args) == 2 {
				o.ociRef = args[1]
			}
			var err error
			if o.registry, err = cmd.Flags().GetString(modulePublishRegistryFlag); err != nil {
				return err
			}
			if o.version, err = cmd.Flags().GetString(modulePublishVersionFlag); err != nil {
				return err
			}
			if o.username, err = cmd.Flags().GetString(modulePublishUsernameFlag); err != nil {
				return err
			}
			if o.password, err = cmd.Flags().GetString(addonPassword); err != nil {
				return err
			}
			if o.force, err = cmd.Flags().GetBool(modulePublishForceFlag); err != nil {
				return err
			}
			if o.dryRun, err = cmd.Flags().GetBool(modulePublishDryRunFlag); err != nil {
				return err
			}

			var cli client.Client
			if o.ociRef == "" {
				if cli, err = c.GetClient(); err != nil {
					return err
				}
			}
			return o.run(cmd.Context(), cli, cmd.OutOrStdout())
		},
	}
	cmd.Flags().String(modulePublishRegistryFlag, "", "The configured module registry to publish to. Empty means the configured default.")
	cmd.Flags().String(modulePublishVersionFlag, "", "Override the artifact tag. Must be semver, and does not bypass version immutability.")
	cmd.Flags().Bool(modulePublishForceFlag, false, "Overwrite an already-published version.")
	cmd.Flags().Bool(modulePublishDryRunFlag, false, "Print the target reference, tag, and annotations without pushing.")
	cmd.Flags().String(modulePublishUsernameFlag, "", "Registry username. Empty uses the docker credential chain.")
	cmd.Flags().String(addonPassword, "", "Registry password. Empty uses the docker credential chain.")
	cmd.Flags().Bool(addonPasswordStdin, false, "Read the registry password from stdin.")
	return cmd
}

// run validates the tree, resolves the target registry, and publishes. Nothing
// reaches a registry until the module parses and the target is known to be OCI.
func (o *modulePublishOptions) run(ctx context.Context, cli client.Client, out io.Writer) error {
	if o.registry != "" && o.ociRef != "" {
		return fmt.Errorf("--%s cannot be combined with a positional OCI reference; pass one or the other", modulePublishRegistryFlag)
	}

	artifact, err := pkgmodule.PackageModule(o.dir, o.version)
	if err != nil {
		return err
	}

	reg, err := o.resolveTarget(ctx, cli)
	if err != nil {
		return err
	}

	ref, err := pkgaddon.OCIChartRef(reg, artifact.Module.Name, artifact.Tag)
	if err != nil {
		return err
	}

	if o.dryRun {
		fmt.Fprintf(out, "Would publish %s\n", ref)
		for _, key := range sortedAnnotationKeys(artifact.Annotations) {
			fmt.Fprintf(out, "  %s: %s\n", key, artifact.Annotations[key])
		}
		return nil
	}

	if !o.force {
		exists, err := o.tagExists(ctx, reg, artifact.Module.Name, artifact.Tag)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("%s is already published; bump version in %s/_module.cue and publish again, or pass --%s to overwrite",
				ref, o.dir, modulePublishForceFlag)
		}
	}

	if err := o.push(ctx, reg, artifact.Module.Name, artifact.Tag, artifact.Archive); err != nil {
		return publishError(ref, err)
	}
	fmt.Fprintf(out, "Published %s\n", ref)
	return nil
}

// resolveTarget returns the registry to publish to: the positional OCI
// reference when given, otherwise the named or default configured registry,
// which requires a cluster. A non-OCI registry is rejected here, before any
// network call.
func (o *modulePublishOptions) resolveTarget(ctx context.Context, cli client.Client) (pkgaddon.Registry, error) {
	if o.ociRef != "" {
		return pkgaddon.Registry{
			Name: o.ociRef,
			OCI:  &pkgaddon.OCIAddonSource{URL: o.ociRef, Username: o.username, Token: o.password},
		}, nil
	}
	if cli == nil {
		return pkgaddon.Registry{}, fmt.Errorf("publishing to a configured registry needs cluster access; pass an OCI reference to publish without a cluster")
	}
	reg, err := pkgmodule.ResolveRegistry(ctx, pkgmodule.NewStore(cli), o.registry)
	if err != nil {
		return pkgaddon.Registry{}, err
	}
	if reg.OCI == nil {
		return pkgaddon.Registry{}, fmt.Errorf("module registry %q is a %s source; vela module publish supports OCI/ECR only",
			reg.Name, pkgmodule.SourceTypeName(reg))
	}
	if o.username != "" {
		reg.OCI.Username = o.username
	}
	if o.password != "" {
		reg.OCI.Token = o.password
	}
	return reg, nil
}

// publishError turns a registry rejection into a message naming the fix. ECR
// creates no repository on push, and an IMMUTABLE repository refuses a tag
// move no matter what the client asks for.
func publishError(ref string, err error) error {
	switch {
	case pkgaddon.IsOCIRepositoryNotFound(err):
		return fmt.Errorf("the repository for %s does not exist; create it in the registry first (ECR does not create repositories on push): %w", ref, err)
	case pkgaddon.IsOCITagImmutable(err):
		return fmt.Errorf("%s cannot be overwritten because the repository rejects tag changes; bump version in _module.cue and publish a new version: %w", ref, err)
	default:
		return fmt.Errorf("failed to publish %s: %w", ref, err)
	}
}

// sortedAnnotationKeys returns the annotation keys in sorted order so dry-run
// output is stable.
func sortedAnnotationKeys(annotations map[string]string) []string {
	keys := make([]string, 0, len(annotations))
	for key := range annotations {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
```

Then mount it, in `references/cli/module-registry.go:63`:

```go
	cmd.AddCommand(NewModuleRegistryCommand(c, ioStreams), NewModulePublishCommand(c, ioStreams), NewModuleDeployCommand(c, ioStreams))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CGO_ENABLED=0 go test ./references/cli/ -run 'TestModulePublish' -count=1 -v`
Expected: PASS, every subtest.

- [ ] **Step 5: Confirm the package's other failures are pre-existing**

Run: `CGO_ENABLED=0 go test ./references/cli/ -count=1 2>&1 | tail -25`

`TestCli`, `TestNewDefinitionGenAPICommand`, and the `top/*` tests need a live cluster and already fail on this branch. Compare against a baseline worktree before blaming your change, as in Task 2 Step 5.

- [ ] **Step 6: Commit**

```bash
git add references/cli/module-publish.go references/cli/module-publish_test.go references/cli/module-registry.go
git commit -m "feat(module): add vela module publish with validation, dry run, and immutability"
```

---

### Task 4: Live registry round-trip and the fetch integration hook

**Files:**
- Create: `pkg/module/publish_integration_test.go` (build tag `integration`)
- Modify: `pkg/module/service/fetch_integration_test.go:59-70` (replace the `publishAndFetch` placeholder)

**Interfaces:**
- Consumes: `PackageModule`, `Artifact`, `AnnotationModule`, `AnnotationLines`, `AnnotationEnabledLines` (Task 1); `pkgaddon.PushOCIChart`, `pkgaddon.OCIChartRef`, `pkgaddon.PullOCIChartFiles` (Task 2 and existing code); `github.com/google/go-containerregistry/pkg/registry`, `.../pkg/v1/remote`, `.../pkg/name`.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing integration test**

Create `pkg/module/publish_integration_test.go`:

```go
//go:build integration
// +build integration

/*
Copyright 2021 The KubeVela Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package module

import (
	"context"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	ggcrregistry "github.com/google/go-containerregistry/pkg/registry"
	"github.com/google/go-containerregistry/pkg/authn"
	"github.com/google/go-containerregistry/pkg/name"
	"github.com/google/go-containerregistry/pkg/v1/remote"
	"github.com/stretchr/testify/require"

	"github.com/oam-dev/kubevela/pkg/addon"
)

// TestPublishRoundTripInProcessRegistry publishes the s3 fixture to an
// in-process OCI registry, reads the manifest back to check the tag and the
// annotations, then pulls the artifact through the same code the module fetch
// uses and asserts an equal Module.
func TestPublishRoundTripInProcessRegistry(t *testing.T) {
	server := httptest.NewServer(ggcrregistry.New())
	defer server.Close()
	host := strings.TrimPrefix(server.URL, "http://")

	reg := addon.Registry{Name: "local", OCI: &addon.OCIAddonSource{URL: "oci://" + host + "/modules"}}
	publishAndAssert(t, reg, host+"/modules", name.Insecure)
}

// TestPublishRoundTripECR runs the same assertions against a real ECR
// repository prefix when MODULE_ECR_REGISTRY is set, for example
// 123456789012.dkr.ecr.us-west-2.amazonaws.com/modules. Credentials come from
// the docker credential chain, so `aws ecr get-login-password | docker login`
// or docker-credential-ecr-login must be in place. The repository
// <prefix>/s3 must already exist.
func TestPublishRoundTripECR(t *testing.T) {
	target := os.Getenv("MODULE_ECR_REGISTRY")
	if target == "" {
		t.Skip("set MODULE_ECR_REGISTRY to publish against a real ECR registry")
	}
	reg := addon.Registry{Name: "ecr", OCI: &addon.OCIAddonSource{URL: target}}
	publishAndAssert(t, reg, strings.TrimPrefix(strings.TrimPrefix(target, "oci://"), "https://"))
}

func publishAndAssert(t *testing.T, reg addon.Registry, repoPrefix string, refOpts ...name.Option) {
	t.Helper()
	ctx := context.Background()

	source, err := ParseModuleDir("testdata/modules/s3")
	require.NoError(t, err)

	art, err := PackageModule("testdata/modules/s3", "")
	require.NoError(t, err)
	require.NoError(t, addon.PushOCIChart(ctx, reg, source.Name, art.Tag, art.Archive))

	ref, err := name.NewTag(repoPrefix+"/"+source.Name+":"+art.Tag, refOpts...)
	require.NoError(t, err)
	desc, err := remote.Get(ref, remote.WithAuthFromKeychain(authn.DefaultKeychain), remote.WithContext(ctx))
	require.NoError(t, err)
	manifest, err := desc.Image()
	require.NoError(t, err)
	mf, err := manifest.Manifest()
	require.NoError(t, err)
	require.Equal(t, source.Name, mf.Annotations[AnnotationModule])
	require.Equal(t, "v1", mf.Annotations[AnnotationLines])
	require.Equal(t, "v1", mf.Annotations[AnnotationEnabledLines])

	files, err := addon.PullOCIChartFiles(ctx, reg, source.Name, art.Tag)
	require.NoError(t, err)
	pulled := map[string][]byte{}
	for _, f := range files {
		pulled[f.Name] = f.Data
	}
	fetched, err := ParseModule(fstestMapFS(pulled))
	require.NoError(t, err)
	require.Equal(t, source, fetched)
}
```

`fstestMapFS` comes from `publish_test.go` (Task 1) and is visible here because both files are in package `module`.

Note the file names: `loader.LoadArchiveFiles` (which `PullOCIChartFiles` returns through) drops the archive's leading `<chartName>/` segment (`helm/pkg/chart/loader/archive.go:151`), so `BufferedFile.Name` is already relative to the chart root and must not be prefix-stripped again. The production fetch path looks different only because `addon.MemoryReader.RelativePath` (`pkg/addon/reader_memory.go:55`) re-adds the module name before `readerFS` trims it back off.

- [ ] **Step 2: Run the integration test to verify it fails, then passes**

Run: `CGO_ENABLED=0 go test -tags integration ./pkg/module/ -run 'TestPublishRoundTripInProcessRegistry' -count=1 -v`

Expected on first run: PASS if Tasks 1 and 2 are correct. If the in-process registry rejects the push, capture the exact error before changing anything: the likely cause is a manifest media type the registry validates. Report the error rather than reshaping the artifact, because the artifact shape is fixed by what the module fetch pulls.

- [ ] **Step 3: Replace the fetch placeholder**

In `pkg/module/service/fetch_integration_test.go`, replace the body of `publishAndFetch` (currently a `t.Skip` at :64) with a real publish through the packages rather than the binary:

```go
func publishAndFetch(t *testing.T, target string, reg addon.Registry) *module.Module {
	t.Helper()
	ctx := context.Background()

	art, err := module.PackageModule("../testdata/modules/s3", "")
	require.NoError(t, err)
	if reg.OCI == nil {
		t.Skip("publish supports OCI/ECR only; git catalog publish is out of scope (GWCP-106685)")
	}
	require.NoError(t, addon.PushOCIChart(ctx, reg, art.Module.Name, art.Tag, art.Archive))

	mod, err := NewService(fakeStore{regs: []addon.Registry{reg}}).FetchModule(ctx, reg.Name, art.Module.Name)
	require.NoError(t, err)
	return mod
}
```

The `target` parameter becomes unused; rename it to `_ string` and update the two call sites at :42 and :45 accordingly if the compiler complains. `fakeStore` already exists in `fetch_test.go:78`, and both files are in package `service`.

- [ ] **Step 4: Verify the fetch integration file still compiles**

Run: `CGO_ENABLED=0 go vet -tags integration ./pkg/module/... && CGO_ENABLED=0 go test -tags integration ./pkg/module/service/ -run TestFetchModule_RoundTrip -count=1 -v`
Expected: vet silent; the round-trip test skips with "set MODULE_GIT_REGISTRY and MODULE_OCI_REGISTRY" because those variables are unset. A skip here is the correct result, not a failure.

- [ ] **Step 5: Full verification**

Run each and report the result verbatim:

```bash
CGO_ENABLED=0 go build ./...
CGO_ENABLED=0 go vet ./pkg/module/... ./pkg/addon/... ./references/cli/...
CGO_ENABLED=0 go test ./pkg/module/... -count=1
CGO_ENABLED=0 go test -tags integration ./pkg/module/ -run TestPublishRoundTrip -count=1
CGO_ENABLED=0 go test ./pkg/addon/... ./references/cli/ -count=1
gofmt -l pkg/module pkg/addon references/cli
```

`golangci-lint` cannot run in this container (the installed binary rejects the repo config with "unsupported version of the configuration"). Record it as not run rather than as passing.

- [ ] **Step 6: Commit**

```bash
git add pkg/module/publish_integration_test.go pkg/module/service/fetch_integration_test.go
git commit -m "test(module): round-trip publish against an in-process OCI registry and real ECR"
```

---

## Self-review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| R1.1 `--registry` resolves an OCI registry; positional `<oci-ref>` targets directly | Task 3 (`resolveTarget`, flag and arg tests) |
| R1.2 validate with the parser before any push | Task 1 (`PackageModule` parses first), Task 3 (`run` packages before resolving, `TestModulePublishFailsBeforePush`) |
| R1.3 a git registry target is rejected with an OCI-only message | Task 3 (`resolveTarget`, git-registry test case) |
| R2.1 tag from `_module.cue version` | Task 1 (`Artifact.Tag`), Task 4 (manifest tag assertion) |
| R2.2 `--version` overrides the tag | Task 1 (`TestPackageModuleVersionOverride`), Task 3 (`TestModulePublishVersionOverride`) |
| R3.1 an existing version is rejected, directing at a version bump | Task 3 (`run` immutability branch), Task 2 (`OCIChartTagExists`) |
| R3.2 `--force` overrides | Task 3 (`force` skips the check) |
| R4.1 annotations record the module and its lines | Task 1 (`moduleAnnotations`), Task 4 (manifest annotation assertions) |
| R4.2 pull back and parse yields an equal Module | Task 1 (`TestPackageModuleRoundTrip`), Task 4 (live pull through `PullOCIChartFiles`) |
| R5.1 auth through the docker/ECR credential chain, no new auth model | Task 2 (reuses `newOCIClient`, which Helm builds with `NewClientWithDockerFallback`); documented, plus the ECR-gated test |
| R5.2 validation failure pushes nothing and exits non-zero | Task 3 (`TestModulePublishFailsBeforePush` asserts zero push calls) |

ECR repository creation, `IMMUTABLE` tag behaviour, and the loopback plain-HTTP rule are design decisions recorded in the design document; the first two surface as messages in Task 3's `publishError` and the third is implemented in Task 2.

**Placeholder scan:** no TBDs, and every code step carries the code to write. The one judgement call left to the implementer is Task 4 Step 2's failure path, which says to report the error rather than reshape the artifact.

**Type consistency:** `Artifact` fields (`Module`, `Tag`, `Annotations`, `Archive`) are used with those names in Tasks 3 and 4. `push` and `tagExists` seam signatures match `pkgaddon.PushOCIChart` and `pkgaddon.OCIChartTagExists` exactly, including the leading `context.Context`. `fstestMapFS` is defined in Task 1 and reused in Task 4. `chartTagLister` is declared in Task 2's production file and swapped by `ociTagListerForTest`, also in that file.
