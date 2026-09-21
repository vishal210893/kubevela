I would like to nominate myself as a reviewer of KubeVela.

I'm a Software Engineer at [Guidewire](https://www.guidewire.com/) and have been actively contributing across `kubevela`, `workflow`, `vela-go-definitions`, `kubevela-core-api`, `catalog`, and the docs site. I'd like to continue contributing as a reviewer and help with code quality, triage, and reviews in the areas I've been working in: **defkit / CUE generation, the Helm chart component, workflow step definitions, post-dispatch trait lifecycle, and security hardening**.

### Contribution summary (across the KubeVela org)

- **33 merged PRs**, **47 PRs authored**, **28 PRs reviewed**, **5 issues filed**
- Repos: `kubevela`, `kubevela.github.io`, `workflow`, `vela-go-definitions`, `kubevela-core-api`, `catalog`

### Merged contributions (selected)

**kubevela/kubevela**
- https://github.com/kubevela/kubevela/pull/7225 — Feat: support `extraEnvs` on vela-core to control `CUE_EXPERIMENT`
- https://github.com/kubevela/kubevela/pull/7213 — Feat: new `deploy-components` workflow step
- https://github.com/kubevela/kubevela/pull/7064 — Feat: defkit API completeness
- https://github.com/kubevela/kubevela/pull/7030 — Feat: eager status for post-dispatch
- https://github.com/kubevela/kubevela/pull/7053 — Fix: duration format handling + `StringParam` enum support
- https://github.com/kubevela/kubevela/pull/7047 — Fix: `status.details` CUE import statements now compile correctly
- https://github.com/kubevela/kubevela/pull/7041 — Fix: defkit CUE generation for task health, nested arrays, patch traits
- https://github.com/kubevela/kubevela/pull/6931 — Feat(logging): colorized dev logging via `dev-logs`
- https://github.com/kubevela/kubevela/pull/6919 — Fix: webhook TLS caBundle breakage during failed Helm upgrades
- https://github.com/kubevela/kubevela/pull/6774 — Feat(validation): fail-fast CUE validation for required parameters
- https://github.com/kubevela/kubevela/pull/6964 — Chore: graceful skip for missing definition directories in install script

**kubevela/workflow**
- https://github.com/kubevela/workflow/pull/234 — Feat: add envVar + `CUE_EXPERIMENT` feature gate to vela-workflow
- https://github.com/kubevela/workflow/pull/231 — Fix: register `oam/v1alpha1` types on manager scheme for `workflowRef`
- https://github.com/kubevela/workflow/pull/223 — Chore: workflow step definitions refactoring and enhancement

**kubevela/vela-go-definitions**
- https://github.com/kubevela/vela-go-definitions/pull/3 — Feat: E2E test automation framework for defkit X-Definitions
- https://github.com/kubevela/vela-go-definitions/pull/6 — Chore: convert workflow step definitions to defkit + fix CI
- https://github.com/kubevela/vela-go-definitions/pull/10 — Chore: update defkit API calls for API completeness

**kubevela/catalog & kubevela-core-api**
- https://github.com/kubevela/catalog/pull/791 — Feat: add `enableCueExpVariable` to gate `CUE_EXPERIMENT`
- https://github.com/kubevela/kubevela-core-api/pull/16 — Bump Go to 1.23.8 + K8s deps to v0.31.10

**Docs**
- https://github.com/kubevela/kubevela.github.io/pull/1421 — defkit definitions documentation
- https://github.com/kubevela/kubevela.github.io/pull/1415 — advanced debugging guides (webhook / remote / multicluster)
- https://github.com/kubevela/kubevela.github.io/pull/1357 — CUE validation documentation

### Community blog post

Beyond code, I authored a deep-dive blog article for the KubeVela site:

- https://github.com/kubevela/kubevela.github.io/pull/1430 — **Deep dive: the KubeVela ResourceTracker pattern and self-healing reconciliation** (merged)

### Reviews (selected)

- https://github.com/kubevela/kubevela/pull/7088
- https://github.com/kubevela/kubevela/pull/7080
- https://github.com/kubevela/kubevela/pull/7008
- https://github.com/kubevela/workflow/pull/224
- https://github.com/kubevela/workflow/pull/221
- https://github.com/kubevela/kubevela.github.io/pull/1415
- https://github.com/kubevela/kubevela-core-api/pull/16

I'd be honored to continue contributing as a reviewer and help keep the community healthy.

cc @anoop2811 @briankane @jguionnet @FogDong @StevenLeiZhang @charlie0129 @sunny0826 @yangsoon @leejanee @HanMengnan @nuclearwu @zxbyoyoyo @zhaohuiweixiao @suwliang3

Welcome sponsorship / voting from Approvers per https://github.com/kubevela/community/blob/main/community-membership.md
