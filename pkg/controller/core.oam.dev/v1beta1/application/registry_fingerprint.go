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

package application

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	goerrors "errors"
	"fmt"
	"sort"
	"strings"
	"sync"

	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	"github.com/oam-dev/kubevela/pkg/module"
	"github.com/oam-dev/kubevela/pkg/registry/component"
)

// Component types whose content lives in a remote registry rather than in the
// Application. Defined in vela-templates/definitions/internal/component/.
const (
	addonComponentType  = "addon"
	moduleComponentType = "module"
)

// Suffix shape for the workflow-revision token that workflow.go appends to
// desiredRev when the fingerprint helper returns a non-empty digest:
// "<base><registryRevSuffixSeparator><registryRevSuffixHexLen-char hex>".
//
// Deliberately the same shape as the valuesFrom suffix, and always appended
// after it, so the two compose into one token and each can prefix-match its
// own half. The hex length encodes 128 bits of SHA-256.
const (
	registryRevSuffixSeparator = "-rr-"
	registryRevSuffixHexLen    = 32
)

// registryTrackingBuild identifies this revision-tracking implementation in the
// log, once per process. Whether a running controller contains a given change
// is otherwise unobservable from outside, and mistaking a stale binary for a
// broken fix costs far more than one log line. Bump it when the read or
// revision semantics change.
const registryTrackingBuild = "content-revision-v2"

var buildMarkerOnce sync.Once

// Resolved registries, and the list of them, reused for as long as a content
// revision is. Resolving one reads a ConfigMap and a Secret, and this runs on
// every reconcile of every Application naming a remote package; ConfigMap
// caching is feature-gated and Secrets are not cached at all, so without this
// the gate would add API reads to every reconcile.
var (
	resolvedRegistryMemo = component.NewTTLMemo[component.Registry](component.ContentRevisionMemoTTL)
	registryListMemo     = component.NewTTLMemo[[]component.Registry](component.ContentRevisionMemoTTL)
)

// addonComponentProperties is the subset of a type: addon component's
// properties that identifies which package it resolves to. Other fields are
// ignored so the helper is resilient to schema additions.
type addonComponentProperties struct {
	Addon    string `json:"addon"`
	Version  string `json:"version,omitempty"`
	Registry string `json:"registry,omitempty"`
}

// moduleComponentProperties is the same for a type: module component.
type moduleComponentProperties struct {
	Module   string `json:"module"`
	Version  string `json:"version,omitempty"`
	Registry string `json:"registry,omitempty"`
}

// computeRegistryRevisionFingerprint walks every type: addon and type: module
// component in the Application, asks each one's registry what it currently
// holds for that package, and returns a stable sha256 hex digest over the
// answers. Returns "" when the Application declares neither type, so the
// workflow gate is left untouched for every other Application.
//
// The digest is appended to desiredRev as a suffix. A package whose content
// moved therefore moves the workflow gate, which is the only way a change in a
// registry reaches a running Application: once every step has succeeded the
// workflow executor returns without running any of them, so nothing re-renders
// and nothing re-reads the registry. StateKeep meanwhile keeps re-applying the
// manifest captured at the last render, so without this the Application would
// hold the pre-push content indefinitely.
//
// Errors are the caller's cue to reuse the previous suffix rather than to fail
// the reconcile. A registry that cannot be reached says nothing about whether
// the package moved, and treating silence as a move would restart the workflow
// on every reconcile -- the loop that exhausts a rate limit and then keeps it
// exhausted. Conditions that are not evidence of a move are skipped here
// instead: a source that cannot report a revision, and a package the registry
// does not carry. The latter is self-healing, because the package appearing
// later adds a line and so moves the digest.
func computeRegistryRevisionFingerprint(ctx context.Context, cli client.Client, app *v1beta1.Application) (string, error) {
	if app == nil || len(app.Spec.Components) == 0 {
		return "", nil
	}

	var lines []string
	for _, comp := range app.Spec.Components {
		if err := ctx.Err(); err != nil {
			return "", err
		}
		if comp.Type != addonComponentType && comp.Type != moduleComponentType {
			continue
		}
		if comp.Properties == nil || len(comp.Properties.Raw) == 0 {
			continue
		}
		line, err := componentRevisionLine(ctx, cli, comp.Type, comp.Properties.Raw)
		if err != nil {
			return "", err
		}
		if line != "" {
			lines = append(lines, line)
		}
	}

	if len(lines) == 0 {
		return "", nil
	}

	// Sorted so the digest depends on what the Application resolves to and not
	// on the order its components happen to be written in.
	sort.Strings(lines)
	sum := sha256.Sum256([]byte(strings.Join(lines, "\n")))
	return hex.EncodeToString(sum[:]), nil
}

// componentRevisionLine is one component's contribution to the digest, or ""
// when the component contributes nothing.
func componentRevisionLine(ctx context.Context, cli client.Client, compType string, raw []byte) (string, error) {
	var (
		name, version, registryName string
		reg                         component.Registry
		err                         error
	)

	switch compType {
	case addonComponentType:
		var props addonComponentProperties
		if err := json.Unmarshal(raw, &props); err != nil || props.Addon == "" {
			// Not parseable as the shape this helper needs, or naming no
			// package. Either way the render layer is the right place for the
			// schema error; gating on a parser disagreement is not.
			return "", nil
		}
		name, version, registryName = props.Addon, props.Version, props.Registry
		reg, err = resolveAddonRegistry(ctx, cli, registryName, name)
	case moduleComponentType:
		var props moduleComponentProperties
		if err := json.Unmarshal(raw, &props); err != nil || props.Module == "" {
			return "", nil
		}
		name, version, registryName = props.Module, props.Version, props.Registry
		reg, err = resolveModuleRegistry(ctx, cli, registryName)
	default:
		return "", nil
	}
	if err != nil {
		if skippableRevisionError(err) {
			return "", nil
		}
		return "", err
	}

	revision, err := reg.PackageContentRevision(ctx, name, version)
	if err != nil {
		if skippableRevisionError(err) {
			return "", nil
		}
		return "", err
	}
	buildMarkerOnce.Do(func() {
		klog.InfoS("registry revision tracking active", "build", registryTrackingBuild)
	})
	klog.V(2).InfoS("registry package revision", "type", compType,
		"registry", reg.Name, "package", name, "version", version, "revision", revision)
	return fmt.Sprintf("%s|%s|%s|%s|%s", compType, reg.Name, name, version, revision), nil
}

// skippableRevisionError reports whether an error means "this component
// contributes nothing to the digest" rather than "the answer is unknown".
//
// A source that cannot name a revision never moves the gate, and a package the
// registry does not carry has no revision to report. Neither is evidence that
// anything changed, and neither should stop the other components from being
// fingerprinted.
func skippableRevisionError(err error) bool {
	return goerrors.Is(err, component.ErrRevisionUnsupported) ||
		goerrors.Is(err, component.ErrPackageNotExist)
}

// resolveModuleRegistry mirrors what the module render path resolves, so the
// gate and the render agree on which registry the component reads from.
func resolveModuleRegistry(ctx context.Context, cli client.Client, name string) (component.Registry, error) {
	return resolvedRegistryMemo.Load(moduleComponentType+"|"+name, func() (component.Registry, error) {
		return module.ResolveRegistry(ctx, module.NewStore(cli), name)
	})
}

// resolveAddonRegistry mirrors what the addon render path resolves.
//
// A named registry is that registry. An unnamed one is whichever configured
// registry carries the addon, searched in the order ListRegistries returns,
// which is sorted for exactly this reason -- FindAddonPackagesDetailFromRegistry
// takes the first registry holding the addon, so the gate has to pick the same
// one or it would fingerprint a package the render never reads.
func resolveAddonRegistry(ctx context.Context, cli client.Client, registryName, addonName string) (component.Registry, error) {
	store := component.NewRegistryDataStore(cli)
	if registryName != "" {
		return resolvedRegistryMemo.Load(addonComponentType+"|"+registryName, func() (component.Registry, error) {
			return store.GetRegistry(ctx, registryName)
		})
	}

	registries, err := registryListMemo.Load(addonComponentType, func() ([]component.Registry, error) {
		return store.ListRegistries(ctx)
	})
	if err != nil {
		return component.Registry{}, err
	}
	for i := range registries {
		reg := registries[i]
		if _, err := reg.PackageContentRevision(ctx, addonName, ""); err != nil {
			if skippableRevisionError(err) {
				continue
			}
			return component.Registry{}, err
		}
		return reg, nil
	}
	return component.Registry{}, fmt.Errorf("%q: %w", addonName, component.ErrPackageNotExist)
}
