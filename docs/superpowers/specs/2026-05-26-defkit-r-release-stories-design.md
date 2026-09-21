# Defkit R-Release Stories under GWCP-100434

**Date**: 2026-05-26
**Author**: Vishal Kumar (Gokarna)
**Parent Epic**: [GWCP-100434](https://guidewirejira.atlassian.net/browse/GWCP-100434) — `[Revelstoke] - KubeVela - Defkit enhancements & improvements`
**Branch**: `fix/defkit-changes-for-resource-builder-docs`

## Context

Pod Gokarna owns Defkit (the shared Go framework for KubeVela cloud-OAM authoring). Pod Ajanta is moving cloud components (S3 OAM, DynamoDB OAM) off CUE and onto Go-on-Defkit; the conversion surfaces Defkit gaps and bugs that, left in component code, would drift the framework from its consumers. Epic GWCP-100434 covers two deliverables — upstream Defkit fixes consumable by ATMOS, and a builders-catalog tool — under the additive-only policy.

This spec scopes one slice of that epic: the DynamoDB-driven Defkit work and the supporting framework refactor. It does not cover the builders-catalog tool (separate stories), the S3 OAM port (owned by Ajanta), or any non-additive Defkit changes.

R-release runs **27 May 2026 – 29 Sept 2026** (9 sprints, 13.1 SOL available, Pod size 6). Vishal is Primary, Reetika is Secondary on Epic 2 (Defkit).

## Approach: split into four stories

The user's original request (two stories) was refined: Story 1 (DynamoDB conversion + defkit fixes + new APIs) is split into three smaller sub-stories so each PR stays focused and reviewable, leaving Story D for the `cuegen.go` refactor. Net: four stories under GWCP-100434.

| Key (TBD) | Title | SP | Goal |
|---|---|---|---|
| Story A | Convert DynamoDB OAM component definition from CUE to Defkit (Go) | 1 | Port DynamoDB CUE → Defkit Go; emitted CUE functionally equivalent. |
| Story B | Defkit bug-fix batch: CUE v0.11 list.Concat, auto-detect imports, let-bindings, list-comprehension guards | 1 | Upstream the in-flight Defkit fixes from this branch. |
| Story C | New Defkit APIs to support DynamoDB OAM authoring requirements | 1 | Additive APIs for AWS-resource scaffolding / IAM / tagging / outputs. |
| Story D | Refactor `pkg/definition/defkit/cuegen.go` into focused modules | 1 | Split ~4,020-line file into 4–6 cohesive files, no behavior change. |

### Common Jira fields for all four

- Parent: `GWCP-100434`
- Issue Type: `User Story`
- Pod (`customfield_10026`): `Gokarna` (option id `17512`)
- Component: `OAM Open Source` (id `15410`)
- Story Points (`customfield_10051`): `1`
- Sprint (`customfield_10010`): blank — assign at R-release sprint planning
- Project: `GWCP`

## Story Content

### Story A — DynamoDB OAM CUE → Defkit (Go)

**Summary**: `[Gokarna] Convert DynamoDB OAM component definition from CUE to Defkit (Go)`

**User Story**

As a Gokarna developer maintaining the cloud-OAM authoring framework,
I want to port the existing DynamoDB OAM component definition from CUE to Go using Defkit,
so that Pod Ajanta can author DynamoDB OAM in the same Go-on-Defkit pattern they use for S3 OAM, and so that the porting exercise surfaces concrete Defkit gaps to be fixed upstream (Story B/C).

**Context**

- DynamoDB OAM is currently written in CUE; the conversion is part of GWCP-100434 BDD Scenario 5.
- Defkit lives at `pkg/definition/defkit/` (kubevela repo); Go-loader at `pkg/definition/goloader/`; CUE generator at `pkg/definition/defkit/cuegen.go`.
- This story is scoped strictly to the conversion. Bug-fixes uncovered go to Story B; new APIs needed go to Story C.

**Acceptance Criteria**

- AC1: A Go-authored DynamoDB OAM component definition exists, built on the Defkit fluent builders.
- AC2: `vela def apply-module` (or goloader entry) compiles the Go definition to a `ComponentDefinition` whose emitted CUE is functionally equivalent to today's CUE (diff or equivalence test).
- AC3: An E2E test deploys an Application using the Go-authored DynamoDB component and confirms the workload reconciles on a real cluster.
- AC4: Any Defkit gap surfaced is filed against Story B (bugs) or Story C (new APIs) — no inline workarounds in component code.

**Out of scope**

- Defkit framework fixes (Story B), new Defkit APIs (Story C), `cuegen.go` refactor (Story D), other AWS components (S3, EFS).

---

### Story B — Defkit bug-fix batch

**Summary**: `[Gokarna] Defkit bug-fix batch: CUE v0.11 list.Concat, auto-detect imports, let-bindings, list-comprehension guards`

**User Story**

As a Gokarna developer maintaining Defkit upstream,
I want to land the batch of Defkit bug-fixes uncovered while Pod Ajanta and we ourselves were authoring S3 OAM and DynamoDB OAM components in Go,
so that subsequent component authoring runs on a Defkit release free of these defects and consumers can remove their current workarounds.

**Context — fixes covered**

1. **CUE v0.11 compatibility** — `ArrayConcat` → `list.Concat`. KubeVela has upgraded CUE to v0.11; the previous emission no longer compiles.
2. **Auto-detect required imports for traits** — detection previously skipped traits without an explicit `Template()` function. Must run for every trait.
3. **Emit let-bindings before output block** — let-bindings emitted after `output: { ... }` produce broken CUE.
4. **Preserve guard `if` clauses in list comprehensions** — emission previously dropped the guard clause, producing incorrect CUE.

Several fixes are already in-flight on branch `fix/defkit-changes-for-resource-builder-docs` (commits `1ac24ed08`, `4c5dd78ac`, `1af849377`, `fe05c6fcb`); this story drives them to merge with tests and release.

**Acceptance Criteria**

- AC1: Upstream PR(s) merged into kubevela/kubevela for each of the four defects.
- AC2: A new test in `cuegen_test.go` (or companions) per fix; existing tests stay green.
- AC3: Release notes document each fix; a Defkit release tag carrying the fixes is published.
- AC4: ATMOS consumption path documented (per upstream-first policy).
- AC5: At least one previously-needed workaround removed from S3 OAM and/or DynamoDB OAM code as a follow-up.

**Out of scope**

- New APIs (Story C), DynamoDB conversion (Story A), `cuegen.go` refactor (Story D).

---

### Story C — New Defkit APIs

**Summary**: `[Gokarna] New Defkit APIs to support DynamoDB OAM authoring requirements`

**User Story**

As a Defkit author working on DynamoDB OAM (and future cloud OAM components),
I want first-class Defkit APIs for the patterns that today require workarounds or raw CUE blocks,
so that the component code stays idiomatic Defkit and the framework compounds velocity for every next cloud OAM component (epic ROI).

**Context**

During Story A we identify the specific missing APIs. Likely categories: AWS-resource scaffolding helpers shared across S3/DynamoDB/EFS; IAM policy builder; tag-applier; output / status patterns for AWS resources (ARN, region, output schemas); composability gaps in existing Component / Trait / Param / Template / Resource chains.

**Acceptance Criteria**

- AC1: A scoped list of new Defkit APIs documented (signatures, intent, owner, target release) by end of triage.
- AC2: Each prioritized API implemented as an **additive** enhancement to Defkit (no breaking changes, per epic policy).
- AC3: Tests + godoc + a short example land in `pkg/definition/defkit/`.
- AC4: DynamoDB OAM (Story A) consumes the new APIs without raw CUE escape hatches.
- AC5: PRs upstreamed to kubevela/kubevela; Defkit release carries the new APIs; ATMOS consumption path documented.

**Out of scope**

- Existing-API bug-fixes (Story B), DynamoDB conversion itself (Story A), `cuegen.go` refactor (Story D).

---

### Story D — Refactor `cuegen.go`

**Summary**: `[Gokarna] Refactor pkg/definition/defkit/cuegen.go into focused modules`

**User Story**

As a Defkit maintainer adding new APIs and fixing bugs as part of the R-release Defkit stream,
I want `cuegen.go` split into focused modules with clearer responsibilities and adequate unit-test coverage,
so that Story B fixes and Story C new APIs land safely and reviewers can hold the file in context.

**Context**

`pkg/definition/defkit/cuegen.go` is ~4,020 lines (was ~3,390 lines when GWCP-100874 wrapped). It contains parameter-schema generation, template emission, field-tree writing, conditional rendering, helpers (`writeMapBody`, `writeConcatHelper`), CUE collection-op handlers, and import detection. Multiple Story B patches concurrently touch the same file, raising review/merge risk.

The refactor is mechanical and additive — no behavior change.

**Acceptance Criteria**

- AC1: `cuegen.go` is split into 4–6 focused files under `pkg/definition/defkit/` (e.g. `cuegen_emit.go`, `cuegen_imports.go`, `cuegen_collections.go`, `cuegen_helpers.go`); names land via PR review.
- AC2: Every existing exported symbol keeps its current signature and behavior; no CUE-output diff against the baseline test fixtures.
- AC3: Existing tests in `cuegen_test.go` stay green; new focused unit tests cover at least the import-detection and emit helpers extracted in the split.
- AC4: PR upstreamed to kubevela/kubevela; release notes mention the internal refactor.

**Out of scope**

- New APIs (Story C), bug-fixes (Story B), DynamoDB conversion (Story A), renaming exported symbols / changing the Defkit public surface.

## Verification

After all four stories are merged:

1. **Story A**: `make build` then run a focused E2E that applies the Go-authored DynamoDB OAM component; confirm `ComponentDefinition` is created and Application reconciles.
2. **Story B**: `go test ./pkg/definition/defkit/...` green on the Defkit release tag; manually compile a definition using each affected code path on CUE v0.11.
3. **Story C**: New APIs invoked from Story A; godoc renders; `vela def apply-module` succeeds on a sample component using each new API.
4. **Story D**: `git diff` of generated CUE before/after the refactor is empty across all fixtures; `go test ./pkg/definition/defkit/...` green at every refactor commit.

## References

- Epic: [GWCP-100434](https://guidewirejira.atlassian.net/browse/GWCP-100434)
- Parent epic: [GWCP-97190](https://guidewirejira.atlassian.net/browse/GWCP-97190) (Strategic Roadmap)
- R-release planning: `https://guidewireconfluence.atlassian.net/wiki/spaces/ORANGE/pages/3099197467/2026.Revelstoke+Planning+-+Gokarna`
- Branch with in-flight Story B fixes: `fix/defkit-changes-for-resource-builder-docs`
- Related recent story: [GWCP-100874](https://guidewirejira.atlassian.net/browse/GWCP-100874) (Defkit Documentation Phase 3 — referenced `cuegen.go` at 3,390 lines)
