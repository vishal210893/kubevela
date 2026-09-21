# Nest Application Addon Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate addon compatibility validation beneath the Application webhook package so the filesystem communicates that addon is a component type, not a separately admitted Kubernetes kind.

**Architecture:** The parent `application` package retains feature-gate orchestration, `type: addon` detection, validator injection, and admission error aggregation. The child `application/addon` package owns property parsing, compatibility checks, fail-open behavior, and its focused tests. The dependency remains one-way from parent to child.

**Tech Stack:** Go 1.23.8, controller-runtime admission validation, Kubernetes feature gates, Testify, Ginkgo/Gomega.

## Global constraints

- Make no runtime, chart, feature-gate, logging, error-message, or fail-open semantic changes.
- Keep `addon.NewValidator()`, `addon.ComponentType`, and `(*addon.Validator).ValidateComponents` signatures unchanged.
- The parent package must import `github.com/oam-dev/kubevela/pkg/webhook/core.oam.dev/v1beta1/application/addon` using alias `addonvalidation`.
- Remove the obsolete top-level `pkg/webhook/core.oam.dev/v1beta1/addon` directory completely.
- Preserve existing unstaged `values.yaml`, addon CUE, and untracked files.
- Use `/Users/viskumar/go/go1.23.8/bin/go` for Go commands.

---

### Task 1: Relocate addon validation under Application ownership

**Files:**
- Create: `pkg/webhook/core.oam.dev/v1beta1/application/addon/compat.go`
- Create: `pkg/webhook/core.oam.dev/v1beta1/application/addon/compat_test.go`
- Create: `pkg/webhook/core.oam.dev/v1beta1/application/addon/validator.go`
- Create: `pkg/webhook/core.oam.dev/v1beta1/application/addon/validator_test.go`
- Delete: `pkg/webhook/core.oam.dev/v1beta1/addon/compat.go`
- Delete: `pkg/webhook/core.oam.dev/v1beta1/addon/compat_test.go`
- Delete: `pkg/webhook/core.oam.dev/v1beta1/addon/validator.go`
- Delete: `pkg/webhook/core.oam.dev/v1beta1/addon/validator_test.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/addon_validation.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go`
- Modify: `pkg/webhook/core.oam.dev/v1beta1/application/addon_validation_test.go`

**Interfaces:**
- Preserves: `func NewValidator() *Validator`
- Preserves: `const ComponentType = "addon"`
- Preserves: `func (*Validator) ValidateComponents(context.Context, *v1beta1.Application) field.ErrorList`
- Produces import path: `github.com/oam-dev/kubevela/pkg/webhook/core.oam.dev/v1beta1/application/addon`

- [ ] **Step 1: Add a failing package-ownership test**

Append this test to `application/addon_validation_test.go`:

```go
func TestAddonValidatorLivesUnderApplication(t *testing.T) {
	_, err := os.Stat("addon/validator.go")
	require.NoError(t, err, "addon validator must live under the Application webhook package")

	_, err = os.Stat("../addon")
	require.ErrorIs(t, err, os.ErrNotExist,
		"top-level v1beta1/addon implies a standalone Addon webhook kind")
}
```

Add the standard-library `os` import. The existing file already imports Testify `require`.

- [ ] **Step 2: Run the ownership test and confirm RED**

Run:

```bash
/Users/viskumar/go/go1.23.8/bin/go test ./pkg/webhook/core.oam.dev/v1beta1/application -run TestAddonValidatorLivesUnderApplication -count=1
```

Expected: FAIL because `application/addon/validator.go` does not exist and `../addon` still exists.

- [ ] **Step 3: Relocate the four implementation and test files**

Using `apply_patch`, recreate the four files under `application/addon` with byte-equivalent Go declarations and delete the four originals. Keep `package addon`; do not rename exported or unexported identifiers and do not modify logic.

The resulting child directory must contain exactly:

```text
application/addon/compat.go
application/addon/compat_test.go
application/addon/validator.go
application/addon/validator_test.go
```

- [ ] **Step 4: Update the two parent imports**

In `application/addon_validation.go` and `application/validating_handler.go`, replace:

```go
addonvalidation "github.com/oam-dev/kubevela/pkg/webhook/core.oam.dev/v1beta1/addon"
```

with:

```go
addonvalidation "github.com/oam-dev/kubevela/pkg/webhook/core.oam.dev/v1beta1/application/addon"
```

No call-site changes are required because the child package name and API remain unchanged.

- [ ] **Step 5: Format and run focused tests**

Run:

```bash
/Users/viskumar/go/go1.23.8/bin/gofmt -w \
  pkg/webhook/core.oam.dev/v1beta1/application/addon/*.go \
  pkg/webhook/core.oam.dev/v1beta1/application/addon_validation.go \
  pkg/webhook/core.oam.dev/v1beta1/application/addon_validation_test.go \
  pkg/webhook/core.oam.dev/v1beta1/application/validating_handler.go

/Users/viskumar/go/go1.23.8/bin/go test \
  ./pkg/webhook/core.oam.dev/v1beta1/application/... \
  ./pkg/webhook/core.oam.dev \
  ./pkg/features \
  -count=1
```

Expected: PASS, including the ownership test and all moved validator/compatibility tests.

- [ ] **Step 6: Verify dependency direction and removal**

Run:

```bash
rg 'pkg/webhook/core\.oam\.dev/v1beta1/addon' --glob '*.go' .
test ! -d pkg/webhook/core.oam.dev/v1beta1/addon
rg 'pkg/webhook/core\.oam\.dev/v1beta1/application/addon' \
  pkg/webhook/core.oam.dev/v1beta1/application/*.go
git diff --check
```

Expected: the first `rg` exits `1`; the directory test exits `0`; the second `rg` finds only the two parent imports; `git diff --check` exits `0`.

- [ ] **Step 7: Commit the relocation**

Stage only the moved files, two parent imports, and the ownership test. Verify existing user changes remain unstaged. Commit:

```bash
git commit -m "refactor(webhook): nest addon validation package"
```
