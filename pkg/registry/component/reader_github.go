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

package component

import (
	"context"
	goerrors "errors"
	"fmt"
	"net/http"
	"net/url"
	"path"
	"strings"

	"github.com/google/go-github/v32/github"
	"github.com/pkg/errors"

	"github.com/oam-dev/kubevela/pkg/utils"
)

var _ AsyncReader = &gitReader{}

// gitHelper helps get addon's file by git
type gitHelper struct {
	Client *github.Client
	Meta   *utils.Content
	// readRef pins reads to one exact commit. Empty means the registry's own
	// configured ref, and empty there means the repository's default branch.
	readRef string
	// credential is a digest of the token this helper reads with, so the
	// rate-limit gate can tell two credentials on one repository apart without
	// the secret itself reaching a map key or a log line.
	credential string
}

type gitReader struct {
	h *gitHelper
}

// ListAddonMeta relative path to repoURL/basePath
func (g *gitReader) ListAddonMeta() (map[string]SourceMeta, error) {
	subItems := make(map[string]SourceMeta)
	_, items, err := g.h.readRepo("")
	if err != nil {
		return nil, err
	}
	for _, item := range items {
		// single addon
		if item.GetType() != DirType {
			continue
		}
		addonName := path.Base(item.GetPath())
		addonMeta, err := g.listAddonMeta(g.RelativePath(item))
		if err != nil {
			return nil, errors.Wrapf(err, "fail to get addon meta of %s", addonName)
		}
		subItems[addonName] = SourceMeta{Name: addonName, Items: addonMeta}
	}
	return subItems, nil
}

func (g *gitReader) listAddonMeta(dirPath string) ([]Item, error) {
	_, items, err := g.h.readRepo(dirPath)
	if err != nil {
		return nil, err
	}
	return g.collectFiles(items)
}

// collectFiles flattens a directory listing into its files, descending into
// subdirectories. Split from listAddonMeta so a caller that has already read a
// directory can flatten it without reading it again.
func (g *gitReader) collectFiles(items []*github.RepositoryContent) ([]Item, error) {
	res := make([]Item, 0)
	for _, item := range items {
		switch item.GetType() {
		case FileType:
			res = append(res, item)
		case DirType:
			subItems, err := g.listAddonMeta(g.RelativePath(item))
			if err != nil {
				return nil, err
			}
			res = append(res, subItems...)
		}
	}
	return res, nil
}

// ReadFile read file content from github
func (g *gitReader) ReadFile(relativePath string) (content string, err error) {
	file, _, err := g.h.readRepo(relativePath)
	if err != nil {
		return
	}
	if file == nil {
		return "", fmt.Errorf("path %s is not a file", relativePath)
	}
	return file.GetContent()
}

func (g *gitReader) RelativePath(item Item) string {
	absPath := strings.Split(item.GetPath(), "/")
	if g.h.Meta.GithubContent.Path == "" {
		return path.Join(absPath...)
	}
	base := strings.Split(g.h.Meta.GithubContent.Path, "/")
	// An item shallower than the configured base is not under it, so there is
	// no relative path to cut. Slicing anyway panics, which is worth avoiding
	// for a value that comes back from a registry listing.
	if len(absPath) < len(base) {
		return path.Join(absPath...)
	}
	return path.Join(absPath[len(base):]...)
}

// source identifies what the rate-limit gate holds: the repository together
// with the credential used to read it.
//
// Both halves are needed. Keyed by repository alone, an exhausted anonymous
// entry would refuse a registry that has a working token for the same
// repository. Keyed by credential alone, one repository's refusal would gate
// every other repository the same token reads -- which is admittedly where the
// limit actually lives, since GitHub counts per account, but being wrong in
// that direction blocks work that would have succeeded.
func (h *gitHelper) source() string {
	return h.Meta.GithubContent.Owner + "/" + h.Meta.GithubContent.Repo + "#" + h.credential
}

// readRepo will read relative path (relative to Meta.Path)
func (h *gitHelper) readRepo(relativePath string) (*github.RepositoryContent, []*github.RepositoryContent, error) {
	return h.readRepoCtx(context.Background(), relativePath)
}

// readRepoCtx is readRepo for a caller that has a context to honour. readRepo
// itself is reached through AsyncReader, whose methods take none.
func (h *gitHelper) readRepoCtx(ctx context.Context, relativePath string) (*github.RepositoryContent, []*github.RepositoryContent, error) {
	key := h.source()
	// Asking a source that has already said it is rate limited spends a
	// request to be told the same thing, and spending it is what keeps the
	// limit exhausted past its own reset.
	if err := sourceRateLimit.blocked(key); err != nil {
		return nil, nil, err
	}
	var opts *github.RepositoryContentGetOptions
	if ref := h.ref(); ref != "" {
		opts = &github.RepositoryContentGetOptions{Ref: ref}
	}
	file, items, _, err := h.Client.Repositories.GetContents(ctx, h.Meta.GithubContent.Owner, h.Meta.GithubContent.Repo, path.Join(h.Meta.GithubContent.Path, relativePath), opts)
	if err != nil {
		return nil, nil, holdRateLimit(key, err)
	}
	return file, items, nil
}

// ref is the git reference to read, most specific first: the commit a pinned
// read names, then the branch the registry URL names, then nothing, which
// leaves GitHub to serve the repository's default branch.
//
// Both the revision probe and the content read go through here, which is the
// point. They used to disagree: the probe resolved Meta.GithubContent.Ref --
// which utils.Parse fills in for a .../tree/<branch>/<path> URL -- while
// readRepo passed no options at all and therefore always read the default
// branch. A registry pinned to a release branch was served the default branch
// (a pre-existing bug), and once revisions were compared, a push to the branch
// actually being served would not move the revision.
func (h *gitHelper) ref() string {
	if h.readRef != "" {
		return h.readRef
	}
	return h.Meta.GithubContent.Ref
}

// Revision is the commit the repository's ref points at. It is one request,
// and when lastKnown still holds it is a conditional one: GitHub answers 304
// Not Modified, which does not count against the rate limit at all.
//
// The revision is the whole repository's head, not the package subtree's, so a
// commit anywhere invalidates every package read from this registry. That is
// the safe direction -- a missed change would serve stale definitions
// indefinitely -- and it still collapses the steady state to nothing, because
// the common case is a registry nobody is pushing to.
func (g *gitReader) Revision(ctx context.Context, lastKnown string) (string, error) {
	key := g.h.source()
	if err := sourceRateLimit.blocked(key); err != nil {
		return "", err
	}
	m := g.h.Meta.GithubContent
	// The branch, not h.ref(): a pinned reader holds a commit, and asking for
	// a commit's own SHA would report that it never changes.
	branch := m.Ref
	if branch == "" {
		branch = "HEAD"
	}
	sha, resp, err := g.h.Client.Repositories.GetCommitSHA1(ctx, m.Owner, m.Repo, branch, lastKnown)
	if err != nil {
		// The conditional request was answered "unchanged", which go-github
		// reports as an error because 304 is not a 2xx.
		if resp != nil && resp.StatusCode == http.StatusNotModified {
			return lastKnown, nil
		}
		return "", holdRateLimit(key, err)
	}
	return strings.TrimSpace(sha), nil
}

// PackageContentRevisions is every package in the registry mapped to the git
// tree SHA of its directory.
//
// One listing of the registry's configured path answers for all of them: a
// directory entry's SHA is the tree object it points at, so it moves when
// anything inside that package changes and stays put when a sibling package
// changes. That is the precision Revision cannot offer, for the price Revision
// costs.
//
// The tree SHA is not a commit and must not be handed to AtRevision; the
// contents API resolves a ref as a commit, branch or tag and would not find
// it. It is only ever compared for equality.
func (g *gitReader) PackageContentRevisions(ctx context.Context, lastKnown ContentRevisionSet) (ContentRevisionSet, error) {
	items, etag, err := g.h.listRegistryPath(ctx, lastKnown.Token)
	if err != nil {
		if goerrors.Is(err, errNotModified) {
			return lastKnown, nil
		}
		return ContentRevisionSet{}, err
	}
	revisions := make(map[string]string, len(items))
	for _, item := range items {
		// A package is a directory. A loose file at the registry root is not
		// one, and ListAddonMetaFor already refuses to read it as one.
		if item.GetType() != DirType {
			continue
		}
		sha := item.GetSHA()
		if sha == "" {
			continue
		}
		revisions[path.Base(item.GetPath())] = sha
	}
	return ContentRevisionSet{Token: etag, Revisions: revisions}, nil
}

// errNotModified means the source answered that what the caller already holds
// is still current, so there is nothing to parse.
var errNotModified = goerrors.New("not modified")

// listRegistryPath lists the registry's configured path, conditionally when
// the caller has an ETag from a previous listing, and returns the entries with
// the ETag to reuse next time.
//
// go-github's GetContents sends no If-None-Match, so the request is built by
// hand. It is worth the few lines: this runs on every reconcile of every
// Application naming a package, and GitHub does not charge a 304 against the
// rate limit, so an unchanged registry costs nothing to confirm no matter how
// many Applications ask.
//
// Only the directory form is handled. The registry path holding a file rather
// than packages is a misconfiguration that ListAddonMetaFor already reports
// per package; here it surfaces as a decode error naming the path.
func (h *gitHelper) listRegistryPath(ctx context.Context, etag string) ([]*github.RepositoryContent, string, error) {
	key := h.source()
	if err := sourceRateLimit.blocked(key); err != nil {
		return nil, "", err
	}

	contentPath := (&url.URL{Path: h.Meta.GithubContent.Path}).String()
	endpoint := fmt.Sprintf("repos/%v/%v/contents/%v",
		h.Meta.GithubContent.Owner, h.Meta.GithubContent.Repo, contentPath)
	if ref := h.ref(); ref != "" {
		endpoint += "?ref=" + url.QueryEscape(ref)
	}

	req, err := h.Client.NewRequest(http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, "", err
	}
	if etag != "" {
		req.Header.Set("If-None-Match", etag)
	}

	var items []*github.RepositoryContent
	resp, err := h.Client.Do(ctx, req, &items)
	if err != nil {
		// A conditional request answered "unchanged" is not a failure, but 304
		// is not a 2xx either, so go-github reports it as an error.
		if resp != nil && resp.StatusCode == http.StatusNotModified {
			return nil, etag, errNotModified
		}
		return nil, "", holdRateLimit(key, err)
	}
	return items, resp.Header.Get("ETag"), nil
}

// ListAddonMetaFor lists one package's files, reading only its directory
// instead of the whole registry.
func (g *gitReader) ListAddonMetaFor(name string) (SourceMeta, error) {
	// The name is joined onto the registry's configured path to build the
	// request, so it has to be a plain directory name and nothing else.
	if !IsPackageName(name) {
		return SourceMeta{}, fmt.Errorf("%q: %w", name, ErrPackageNotExist)
	}
	file, dirItems, err := g.h.readRepo(name)
	if err != nil {
		if isGitHubNotFound(err) {
			return SourceMeta{}, fmt.Errorf("%q: %w", name, ErrPackageNotExist)
		}
		return SourceMeta{}, err
	}
	// A package is a directory. Naming a file at the registry root used to
	// read back as a package with no files, which reaches the caller as
	// "the module is empty" rather than "there is no such module" -- the
	// unscoped listing reported absence, because it only ever offered
	// directories to look up.
	if file != nil || len(dirItems) == 0 {
		return SourceMeta{}, fmt.Errorf("%q: %w", name, ErrPackageNotExist)
	}
	items, err := g.collectFiles(dirItems)
	if err != nil {
		return SourceMeta{}, err
	}
	return SourceMeta{Name: name, Items: items}, nil
}

// isGitHubNotFound reports whether err is GitHub answering that the path does
// not exist, as opposed to refusing to say. A private repository read without
// a usable token answers 404 as well, so this is only consulted on a path that
// was already reachable enough to ask about.
func isGitHubNotFound(err error) bool {
	var resp *github.ErrorResponse
	return errors.As(err, &resp) && resp.Response != nil && resp.Response.StatusCode == http.StatusNotFound
}
