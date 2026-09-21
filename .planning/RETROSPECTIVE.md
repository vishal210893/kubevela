# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

---

## Milestone: v1.0 — defkit Fluent API Completeness

**Shipped:** 2026-03-06
**Phases:** 5 | **Plans:** 13 | **Sessions:** ~10

### What Was Built

- Complete param type coverage: `FloatParam.Short/Ignore`, `ForceOptional` on Int/Float/Enum, `StatusDetails` on all 4 definition types
- Full annotation + label system with sorted CUE render, `ToYAML` merge strategy, and status blocks in WorkflowStep/Policy generators
- 7 missing CRD spec fields: `Version`, `ManageWorkload/ControlPlaneOnly/RevisionEnabled`, `ManageHealthCheck`, `ChildResourceKind`, `PodSpecPath`
- 5 API consistency renames across defkit + 102 call sites migrated in vela-go-definitions with zero build errors

### What Worked

- **Pure additions before renames** — Phases 1-3 carried zero downstream risk; renames landed in Phases 4-5 once the API surface was stable. No backtracking required.
- **Phase-level commits** — Clean, signed commit per phase meant git history reads as a feature narrative, not a stream of micro-edits.
- **Atomic rename strategy for FilterPred/Filter swap** — Renaming two methods with overlapping name semantics in one pass prevented intermediate compile failures.
- **Grep-based verification before closing phases** — Zero residual old method names caught by live grep sweeps in both repos before marking each phase done.
- **VERIFICATION.md per phase** — Concrete code-line evidence (file:line) made the milestone audit trivial; no re-investigation required.

### What Was Inefficient

- **Phase 4 needed a gap closure plan (04-03)** — Initial plan assumed all A3/A5 callers were inside defkit; vela-go-definitions had 17+1 call sites that weren't scoped. Discovery cost one extra plan and re-verification cycle. Pre-scan downstream before writing plans for renames.
- **REQUIREMENTS.md checkboxes not updated** — C5 and C6 were implemented in Phase 3 but their checkboxes were never ticked. The 3-source cross-reference caught it at audit time but it created unnecessary triage.
- **No `requirements-completed` frontmatter in SUMMARY.md** — GSD's 3-source verification relies on this field; its absence meant the 3rd verification source was always missing. All plans got "partial" rather than "satisfied" from the matrix, requiring manual override.
- **Nyquist VALIDATION.md never created** — workflow.nyquist_validation is enabled in config but no phases produced VALIDATION.md files. For a pure library refactor this is low-value, but the config toggle should be disabled upfront if Nyquist is intentionally skipped.

### Patterns Established

- **`baseDefinition` embed for shared API fields** — Version, StatusDetails, Annotations all landed on `baseDefinition` and are exposed via 4 thin concrete methods. Future additions should follow this pattern.
- **Nil-conditional CUE blocks** — nil map = omit block; empty map = emit empty block `{}` ; non-empty map = sorted entries. Established across labels, annotations, and version fields.
- **IIFE merge pattern for `ToYAML` annotations** — `func() map[string]any { ... }()` ensures `definition.oam.dev/description` always wins. Adopted uniformly across all 4 ToYAML methods.
- **Conditional boolean emit** — CRD spec booleans use `if field { ... }` in ToYAML, never always-emit. Zero-arg setter, `Is*` getter naming.
- **Receiver-specific method scope for renames** — Before renaming `Fields()` or `Filter()`, confirm the exact receiver type. Other types with identical method names (ConcatHelperBuilder, InCondition, CollectionOp) are left untouched.

### Key Lessons

1. **Scan downstream call sites before writing rename plans.** Running `grep -r "OldMethodName" ../vela-go-definitions` before committing to a plan scope prevents surprise gap closure phases.
2. **Update requirement checkboxes at the same time as committing implementation.** Stale checkboxes add noise at audit time and undermine automated coverage tracking.
3. **Add `requirements-completed` to SUMMARY.md templates.** GSD's 3-source cross-reference is only as strong as its sources; a missing frontmatter field forces manual override at audit time.
4. **Disable `nyquist_validation` in config if the project type doesn't have testable user flows.** A library refactor has no HTTP routes or UI flows; Nyquist VALIDATION.md is meaningless overhead. Set `workflow.nyquist_validation: false` in `.planning/config.json` at project init.
5. **Trait CUE formatter aligns fields with extra spaces.** Test assertions for trait CUE output must use `MatchRegexp` not `ContainSubstring` because `formatCUE(Simplify())` strips quotes and adds padding that breaks exact substring matching.

### Cost Observations

- Model mix: ~100% sonnet (claude-sonnet-4-6 via balanced profile)
- Sessions: ~10 sessions across 1 day
- Notable: Single-day milestone completion for 17 requirements / 5 phases. Phase-level parallelization (where plans were independent) kept total session count low.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | ~10 | 5 | First milestone — baseline established |

### Cumulative Quality

| Milestone | Tests | Build | Zero-Regressions |
|-----------|-------|-------|-----------------|
| v1.0 | 3 pkgs pass | both repos clean | yes — webhook tests unaffected |

### Top Lessons (Verified Across Milestones)

1. Scan all downstream consumers before writing rename plans — prevents unplanned gap closure phases
2. Keep REQUIREMENTS.md checkboxes in sync with implementation — stale docs cost audit time

---
*Last updated: 2026-03-06 after v1.0 milestone*
