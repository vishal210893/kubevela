/*
Copyright 2026 The KubeVela Authors.

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

package component

import (
	"context"
	"fmt"
	"strings"
	"sync"
)

// ErrRevisionUnsupported means this registry source cannot name its revision
// cheaply, so a caller has to read the package to know what it holds.
var ErrRevisionUnsupported = NewError("registry source cannot report a revision")

// PackageRevision names what the registry currently holds for one package,
// without reading the package. Two callers of this in a row cost one small
// request between them, or none at all when the source can revalidate
// conditionally.
//
// lastKnown is the revision the caller holds, or empty. When it is still
// current it is returned unchanged.
//
// The returned string is opaque and only ever compared for equality. It is not
// a version: a git registry reports a commit, an OCI registry a tag and the
// digest behind it, and neither is ordered.
func (r *Registry) PackageRevision(ctx context.Context, name, version, lastKnown string) (string, error) {
	// OCISource, not OCIChartSource: the latter deliberately widens to
	// scheme-less and http:// URLs for the module chart path, and a plain Helm
	// repository served over HTTP matches that spelling too. Asking such a
	// server for a manifest digest fails, and failing a revision probe is worse
	// than not having one -- so only an unambiguous oci:// endpoint takes this
	// branch.
	if oci := r.OCISource(); oci != nil {
		return r.ociPackageRevision(ctx, oci, name, version, lastKnown)
	}
	// A Helm chart repository has no equivalent of a manifest digest, and its
	// index is the thing a caller would have to fetch anyway.
	if r.Helm != nil {
		return "", ErrRevisionUnsupported
	}
	reader, err := r.BuildReader()
	if err != nil {
		return "", err
	}
	revisions, ok := reader.(RevisionReader)
	if !ok {
		return "", ErrRevisionUnsupported
	}
	return revisions.Revision(ctx, lastKnown)
}

// contentRevisionMaps holds one git registry's whole package-to-revision map,
// and contentRevisionValues one OCI package's digest, for ContentRevisionMemoTTL.
//
// Two memos rather than one because the two sources answer at different
// granularities: a git listing produces every package at once, while an OCI
// registry is asked per package and per version. Both are keyed by the
// registry's source identity so that Applications sharing a registry share the
// probe, which is the point -- every Application naming a package asks on
// every one of its own reconciles.
var (
	contentRevisionProbes = NewTTLMemo[ContentRevisionSet](ContentRevisionMemoTTL)
	contentRevisionValues = NewTTLMemo[string](ContentRevisionMemoTTL)
)

// The last set each source returned, kept past the memo's TTL because it
// carries the token that revalidates it. Expiring it with the memo would throw
// away the ETag and turn every probe back into a full listing, which is the
// cost this is here to avoid. One small entry per registry, so it is bounded
// by how many registries a cluster configures.
var (
	lastContentRevisionsMu sync.Mutex
	lastContentRevisions   = map[string]ContentRevisionSet{}
)

func loadLastContentRevisions(key string) ContentRevisionSet {
	lastContentRevisionsMu.Lock()
	defer lastContentRevisionsMu.Unlock()
	return lastContentRevisions[key]
}

func storeLastContentRevisions(key string, set ContentRevisionSet) {
	lastContentRevisionsMu.Lock()
	defer lastContentRevisionsMu.Unlock()
	lastContentRevisions[key] = set
}

// ResetContentRevisionMemo forgets every content-revision probe. It exists for
// tests, which would otherwise carry a probe from one case into the next.
func ResetContentRevisionMemo() {
	contentRevisionProbes.Reset()
	contentRevisionValues.Reset()
	lastContentRevisionsMu.Lock()
	defer lastContentRevisionsMu.Unlock()
	lastContentRevisions = map[string]ContentRevisionSet{}
}

// SourceKey identifies where this registry reads from and with what, so two
// registries pointing at one repository under different credentials are told
// apart and the secret itself never reaches a map key or a log line.
func (r Registry) SourceKey() string {
	var source, secret string
	switch {
	case r.Git != nil:
		source, secret = "git|"+r.Git.URL+"|"+r.Git.Path, r.Git.Token
	case r.Gitee != nil:
		source, secret = "gitee|"+r.Gitee.URL+"|"+r.Gitee.Path, r.Gitee.Token
	case r.Gitlab != nil:
		source, secret = "gitlab|"+r.Gitlab.URL+"|"+r.Gitlab.Repo+"|"+r.Gitlab.Path, r.Gitlab.Token
	case r.OSS != nil:
		source = "oss|" + r.OSS.Endpoint + "|" + r.OSS.Bucket + "|" + r.OSS.Path
	case r.Helm != nil:
		source, secret = "helm|"+r.Helm.URL, r.Helm.Username+"|"+r.Helm.Token
	default:
		source = "unknown"
	}
	return r.Name + "|" + source + "|" + CredentialDigest(secret)
}

// PackageContentRevision names what the registry holds for one package's own
// content, reusing a probe of the same registry made in the last
// ContentRevisionMemoTTL.
//
// It answers a different question from PackageRevision and its result must not
// be used as a read pin; see ContentRevisionReader. A source that cannot
// answer reports ErrRevisionUnsupported, and a package the source does not
// carry reports ErrPackageNotExist. Both are for the caller to skip over
// rather than fail on: neither says anything has moved.
func (r *Registry) PackageContentRevision(ctx context.Context, name, version string) (string, error) {
	key := r.SourceKey()
	if oci := r.OCISource(); oci != nil {
		// Per package and per version, because that is the granularity the
		// digest behind a resolved tag already has.
		return contentRevisionValues.Load(key+"|"+name+"|"+version, func() (string, error) {
			return r.ociPackageRevision(ctx, oci, name, version, "")
		})
	}
	if r.Helm != nil {
		return "", ErrRevisionUnsupported
	}
	set, err := contentRevisionProbes.Load(key, func() (ContentRevisionSet, error) {
		reader, err := r.BuildReader()
		if err != nil {
			return ContentRevisionSet{}, err
		}
		contents, ok := reader.(ContentRevisionReader)
		if !ok {
			return ContentRevisionSet{}, ErrRevisionUnsupported
		}
		next, err := contents.PackageContentRevisions(ctx, loadLastContentRevisions(key))
		if err != nil {
			return ContentRevisionSet{}, err
		}
		storeLastContentRevisions(key, next)
		return next, nil
	})
	if err != nil {
		return "", err
	}
	revision, ok := set.Revisions[name]
	if !ok {
		return "", fmt.Errorf("%q: %w", name, ErrPackageNotExist)
	}
	return revision, nil
}

// ContentRevisionPin returns the revision a package cache should file an entry
// under, and the value its read should be pinned to, when the source can name
// what it holds. ok is false when it cannot, and the caller keeps whatever it
// did before.
//
// The two return values differ because a content revision is not always a read
// pin. For an OCI registry it is: the manifest digest both identifies the
// content and can be pulled by. For git it is a tree SHA, which the contents
// API will not resolve as a ref, so pin is empty and the read is left to take
// the same ref the listing took.
//
// Why a cache must file entries under this revision rather than its own.
// Deciding whether an Application's workflow restarts compares content
// revisions, and deciding whether a package is re-read used to compare commits
// from a different endpoint. Those two answers can disagree: shortly after a
// push the directory listing already reports the new tree while the commit
// endpoint still reports the previous head. The gate then restarts the
// workflow, the read is pinned to the stale commit and returns the previous
// content, and the gate records the new fingerprint regardless. From then on
// the gate matches, nothing restarts, and the Application serves content one
// commit behind for good. Observed twice against a live registry, with the
// rendered value landing exactly one commit behind the gate both times.
//
// Comparing the same revision the gate compares removes the disagreement. An
// unpinned read can only err the other way, returning content newer than the
// revision it is filed under, which the next probe notices and re-reads.
func ContentRevisionPin(ctx context.Context, r Registry, name, version string) (revision, pin string, ok bool) {
	revision, err := r.PackageContentRevision(ctx, name, version)
	if err != nil || revision == "" {
		return "", "", false
	}
	if r.OCISource() != nil {
		return revision, revision, true
	}
	return revision, "", true
}

// ociPackageRevision is the resolved tag and the digest behind it. Both belong
// in the key: the digest alone would miss a move from one tag to another when
// the caller asked for no particular version, and the tag alone would miss a
// re-push of the same tag, which is the ordinary way a module is corrected.
func (r *Registry) ociPackageRevision(ctx context.Context, oci *HelmSource, name, version, lastKnown string) (string, error) {
	repoRef, host := OCIRepoRef(oci.URL, name)
	tag, err := resolveOCITag(ctx, repoRef, host, oci.Username, oci.Token, version)
	if err != nil {
		return "", err
	}
	// Only offer the digest half back to the registry, and only if it was read
	// for this same tag -- a conditional request carrying another tag's digest
	// would be answered 200 anyway, and carrying a composite string would be
	// answered 200 for a digest the registry never issued.
	lastDigest := ""
	if lastTag, digest, found := strings.Cut(lastKnown, "@"); found && lastTag == tag {
		lastDigest = digest
	}
	digest, err := OCIManifestDigest(ctx, repoRef, host, oci.Username, oci.Token, tag, lastDigest, false)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s@%s", tag, digest), nil
}

// ListPackageMeta lists one package's files, reading only that package when the
// source can. Sources that cannot fall back to listing the registry and
// picking the one entry out, which is what every caller used to do.
func (r *Registry) ListPackageMeta(name string) (SourceMeta, error) {
	reader, err := r.BuildReader()
	if err != nil {
		return SourceMeta{}, err
	}
	return ListPackageMeta(reader, name)
}

// ListPackageMeta lists one package from a reader, scoped if the reader
// supports it.
func ListPackageMeta(reader AsyncReader, name string) (SourceMeta, error) {
	// Checked here as well as in the reader: a scoped read turns the name into
	// a request path, and an unscoped one only uses it as a map key, so this is
	// the one place both kinds of source pass through.
	if !IsPackageName(name) {
		return SourceMeta{}, fmt.Errorf("%q: %w", name, ErrPackageNotExist)
	}
	if scoped, ok := reader.(ScopedReader); ok {
		return scoped.ListAddonMetaFor(name)
	}
	metas, err := reader.ListAddonMeta()
	if err != nil {
		return SourceMeta{}, err
	}
	meta, ok := metas[name]
	if !ok {
		return SourceMeta{}, fmt.Errorf("%q: %w", name, ErrPackageNotExist)
	}
	return meta, nil
}
