# KEP-2.20 (Module & API Line Versioning) — Learning Notes

Source: https://github.com/guidewire-oss/kubevela/blob/021a233691e4f03f264a15a988783ad8e2a8213f/design/vela-core/keps/2.20-module-versioning/README.md

Vishal's questions while reading the KEP, with verbatim answers from the chat.

---

## Contents

1. [Q1 — Definition Identity, Naming Convention, Labels/Annotations, and Type Reference Syntax](#q1-explain-definition-identity-definition-naming-convention-definition-labels-and-annotations-and-type-reference-syntax)
2. [Q2 — What does "Form" in Form 1/Form 2/Form 3 refer to?](#q2-what-does-form-in-form-1form-2-or-form-3-refer-to)
3. [Q3 — Resolution Stability Summary, Definition Lock, and lock staleness/recovery](#q3-explain-the-resolution-stability-summary-definition-lock-and-lock-stalenessrecovery)
4. [Q4 — Which "definitions" does the module/apiVersion model apply to: built-in KubeVela defs or addon defs?](#q4-which-definitions-does-the-moduleapiversion-model-apply-to-built-in-kubevela-defs-or-addon-defs)
5. [Q5 — When do you use Form 1 vs Form 2?](#q5-when-do-you-use-form-1-vs-form-2)
6. [Q6 — Explain "Recommended Usage": the contract policy flag and the two-step API line migration](#q6-explain-recommended-usage-the-contract-policy-flag-and-the-two-step-api-line-migration)
7. [Q7 — Real-world worked example: Form 2 vs Form 3](#q7-real-world-worked-example-form-2-vs-form-3)
8. [Q8 — Is an addon just installing definitions for an application to use?](#q8-is-an-addon-just-installing-definitions-for-an-application-to-use)
9. [Q9 — Where does the definition lock actually get written? Give an example.](#q9-where-does-the-definition-lock-actually-get-written-give-an-example)

---

## Q1. Explain Definition Identity, Definition Naming Convention, Definition Labels and Annotations, and Type Reference Syntax.

Think of this as Kubernetes API versioning, applied to KubeVela's own definitions.

### The identity problem

Right now a ComponentDefinition is just a name. `bucket` is `bucket`. If an addon author renames a parameter on it, every app using `bucket` breaks at once, because there's only one `bucket` in the cluster, ever.

KEP-2.20 splits that identity into three parts, the same way Kubernetes splits `apiVersion: apps/v1, kind: Deployment`:

- `module`: which package this comes from. Think API group (`apps`). Example: `aws-s3`. Normally set by the addon controller, but you can hand-set it if you're authoring a definition yourself.
- `apiVersion`: which contract version (`v1`, `v1beta1`, `v2alpha1`), a promise that the parameter schema won't change under you. Also settable by the addon controller or by hand. Validated at admission against the pattern `^v\d+(alpha\d+|beta\d+)?$`, so `v1`, `v2`, `v1beta1`, `v1alpha2` are fine, but `1.0`, `v1.2`, and `latest` get rejected outright.
- `name`: the actual capability, like `kind: Deployment`. Example: `bucket`.

Put them together and `aws-s3/v1/bucket` is the full identity, the "canonical triple." Two new optional fields land on ComponentDefinition, TraitDefinition, WorkflowStepDefinition, and PolicyDefinition to carry the first two: `spec.module` and `spec.apiVersion`.

There's no in-between state. Neither field set means it's a legacy definition, resolved by name only, exactly like today, and nothing changes for existing addons. Both fields set means it's a versioned definition and now plays by the new triple-based rules. Setting only one of the two is disallowed, so there's no ambiguous half-state to reason about, and no partial migration path either. A definition is fully in the new model or fully outside it.

Why not just reuse `spec.version` for this? Because that field already has a job. It's the addon's release tag (`v1.2.3`), stamped automatically by the controller for internal bookkeeping. Operators see it, but app authors were never supposed to reference it directly. `apiVersion` is the new field meant to actually be the stable, user-facing contract.

### Naming convention on the cluster

The actual CR gets named `{module}-{apiVersion}-{name}`, so `aws-s3-v1-bucket`. Ship a v2 line later and you get a second CR, `aws-s3-v2-bucket`, living right next to v1. Both stay installed at once. Apps pick whichever one they reference.

If that computed name would run past 253 characters (the Kubernetes object name limit), the controller truncates it and appends an 8-character hash computed from the full untruncated name, so the suffix stays stable across reconciles instead of drifting around.

Why put the API version before the name instead of after? Because DefinitionRevision already appends its own `-v{N}` counter to track edit history within one definition. `aws-s3-v1-bucket-v3` is the third revision of the v1 bucket definition. If apiVersion came after the name, that revision suffix and the API line would collide in the same position and get confusing fast.

That's a genuinely different mechanism from DefinitionRevision, which already exists today. DefinitionRevision keeps history for one definition, like `git log` on a single file: only one revision is ever "current," the rest sit there for rollback or audit. API lines don't work that way. v1 and v2 are both current at the same time, both actively maintained, and apps choose between them on purpose instead of one superseding the other. It's closer to running two supported major versions of an SDK side by side than to version history. The two mechanisms actually stack: DefinitionRevision keeps tracking edit history inside each API line separately.

One thing to flag: this naming convention is a breaking change for any tooling that hardcodes definition names. Existing addons that don't adopt `_version.cue` keep their current names untouched, so nothing breaks today. The risk shows up only for tooling that starts consuming module-managed definitions and assumes the old naming.

### Labels and annotations

Every module-managed definition gets stamped with a standard set of labels, used for fast lookups by selector:

```
definition.oam.dev/module: aws-s3
definition.oam.dev/api-version: v1
definition.oam.dev/name: bucket
addon.oam.dev/name: aws-s3
```

Plus internal-metadata annotations:

```
addon.oam.dev/version: v1.2.3
addon.oam.dev/managed-by: controller
definition.oam.dev/full-name: aws-s3-v1-bucket
```

And a set of lifecycle annotations that get set dynamically as the definition's state changes, not at install time:

```
definition.oam.dev/deprecated: "true"
definition.oam.dev/deprecated-at: "2026-03-24T10:00:00Z"
definition.oam.dev/disabled: "true"   # set when its _version.cue "enabled" expression evaluates to false
```

The labels are what make Form 2 resolution possible (more on that below). The webhook runs a selector against `definition.oam.dev/api-version` and `definition.oam.dev/name` to find candidates without needing to know the module up front.

### How an app actually points at one

Instead of `type: bucket`, you now get three forms, and the type string is parsed purely by counting slash-separated segments.

`type: aws-s3/v1/bucket`, three segments, is Form 3, fully qualified: module, version, and name all explicit. This is the closest thing to `apiVersion` plus `kind` in raw Kubernetes YAML. It's fully deterministic the moment it's written. No cluster lookup is needed to know exactly which CR it means, because the controller can derive the exact CR name directly from the naming convention and do a plain GET. Use this for anything in git, GitOps, or production.

`type: v1/bucket`, two segments where the first matches `^v\d+`, is Form 2, version-scoped: the API version is explicit but the module isn't named. On first admission, the webhook runs that label selector across all installed modules looking for `api-version=v1, name=bucket`. Exactly one match, and it locks onto that module for this component permanently, storing the resolved triple. More than one match, meaning two different modules both ship a v1/bucket, and admission gets rejected outright with an ambiguity error, telling you to switch to Form 3. There's no "pick the best guess" behavior anywhere in this system.

`type: bucket`, one segment, is Form 1, the legacy path: a plain exact-name GET, nothing else. It only works if that definition has no `spec.module` set at all. If someone later versions a definition that happens to be named `bucket`, this old-style reference gets rejected the moment it tries to resolve to that versioned definition, forcing you onto Form 2 or Form 3 instead. Form 1 never writes anything to the lock. It's completely outside this whole system.

### The four resolution rules

Everything above is really governed by four hard rules, worth memorizing because they explain most of the "why does it fail here" cases:

1. Version is always explicit. There's no fallback where the system infers a version for you. A type string with no version segment isn't treated as a versioned reference at all, it just falls to Form 1.
2. Module is only required when there's ambiguity. Form 2 lets you skip naming the module, but only because the selector can usually find exactly one match.
3. Any ambiguity is a hard failure, always. Not "pick the newest," not "pick the most stable," just reject. There's no ranking logic used to break ties during resolution, ever.
4. Once resolved, `module` and `name` are frozen for that component. Only `apiVersion` is allowed to change afterward, and only by explicitly editing `type` yourself. Trying to change `type` in a way that would alter the module or name gets rejected outright, since that's swapping the contract entirely, not migrating within it.

### Resolution priority order, step by step

Each form follows a strict sequence of checks, and once one step succeeds or fails, nothing after it runs.

Form 3 checks, in order: if a lock already exists for this component, verify the incoming type's module and name still match what's stored, and reject if they don't. Otherwise derive the exact CR name from the naming convention and do a direct GET, rejecting if it's not found. If found, write (or refresh) the lock and accept.

Form 2 checks, in order: if a lock already exists, do a direct GET using the stored module plus the incoming apiVersion and name, no selector involved, and accept or reject on that GET alone. If no lock exists yet, run the global label selector on apiVersion and name, reject with an ambiguity error if more than one result comes back, otherwise store a new lock and accept.

Form 1 checks, in order: do the exact-name GET. Found with no `spec.module` set: accept as legacy, no lock written. Found with `spec.module` set: reject and tell the author to use Form 2 or Form 3. Not found at all: reject as "definition not found."

### Legacy priority is unconditional

One thing that trips people up: if a plain, non-module `bucket` already exists on the cluster, and later someone installs a versioned definition that's also internally labeled `name: bucket` (just under a different module), the plain old one still wins for Form 1. `type: bucket` keeps resolving to the legacy definition, full stop. It does not silently start resolving to the new versioned one. The reasoning is that Form 1 authors have no way to disambiguate further, since `bucket` is already the most specific thing they can write, so the system can't safely reinterpret that reference just because a same-named definition showed up elsewhere. Platform teams introducing a versioned definition under a name that a legacy definition already owns need to know that legacy one keeps winning until it's explicitly removed.

### Stability ordering for API versions

There's also a defined ordering across API lines, used only for reasoning about deprecation, never for picking a winner during resolution (remember, any ambiguity is a hard failure, and this ordering doesn't override that). Stable beats beta beats alpha, regardless of the number attached:

- `vN` (stable) ranks highest, higher N wins: `v2 > v1`.
- `vNbetaM` ranks next, N first then M: `v2beta1 > v1beta2 > v1beta1`.
- `vNalphaM` ranks lowest, same tiebreak order.

So `v1` (stable) always outranks `v2beta1` (beta), which always outranks `v3alpha1` (alpha), no matter what the numbers suggest. If a `v2alpha1` line gets installed next to a stable `v1` line, it does not shadow or replace `v1` in any way. They're two fully separate, independently addressable API lines, and an app author has to explicitly choose which one to reference by writing the full type string.

---

## Q2. What does "form" in Form 1/Form 2, or Form 3 refer to?

"Form" just means which shape the `type:` string takes. It's the KEP's own label for the three accepted ways of writing a type reference, based on how many slash-separated segments the string has.

- Form 1 = 1 segment: `bucket`
- Form 2 = 2 segments: `v1/bucket`
- Form 3 = 3 segments: `aws-s3/v1/bucket`

The number just tracks segment count. It's not a ranking, a version number, or a precedence order. Form 3 isn't "better" than Form 1 in general, they cover different situations: legacy, explicit-but-unpinned, and fully pinned. And it's not a Kubernetes term either. It's vocabulary this KEP made up to talk about its own type-string parsing logic. Nothing else in KubeVela calls anything "Form N."

---

## Q3. Explain the Resolution Stability Summary, Definition Lock, and lock staleness/recovery.

This section is really about one thing: once a component's type gets resolved to a specific definition, that resolution gets written down permanently, and after that the system stops looking at the cluster for that component ever again.

### The stability table, in plain terms

Form 3 (`aws-s3/v1/bucket`): both module and apiVersion are explicit and pinned right in the string. Fully deterministic from the very first admission, no cluster state consulted at all. Recommended for production.

Form 2 (`v1/bucket`): apiVersion is explicit and pinned, but module is only "resolved at first admission" via the selector, then permanently locked afterward. That word "resolved" is the risky part. It depends on whatever's installed on the cluster at the exact moment you first apply it.

Form 1 (`bucket`): neither module nor apiVersion apply here at all. It's completely outside the module system, plain exact-name match, legacy only. The table's footnote clarifies something subtle: if `bucket` happens to have `spec.module` set (someone versioned a definition with that exact name), Form 1 doesn't just quietly fail, admission gets rejected. But that's not really "Form 1 failing." The two models, legacy and versioned, simply don't overlap. Form 1 was never built to address a versioned definition in the first place.

### The definition lock itself

You already know ApplicationRevision as the thing that freezes a spec snapshot at each publish for rollback. This is the same idea applied to binding decisions instead of the whole spec. There's a new field, `ApplicationRevision.spec.definitionLocks`, holding one entry per component: the resolved `{module, apiVersion, name}` triple.

The lifecycle is short: resolve once on first admission, write the triple into the lock, then every later admission just reads that stored triple back out. No selector runs again. No re-resolution happens, ever, for that component. A new v2 line shipping, a brand-new module getting installed, unrelated spec edits, none of it reopens the lock. `.status.services[i].resolvedDefinition` is just a read-only mirror of that lock so a human can see the binding without digging through ApplicationRevision directly. Editing that status field does nothing. The lock is the only thing that actually governs resolution.

### Why Form 2 isn't safe for fresh-cluster GitOps

Picture committing `type: v1/bucket` to git. On cluster A, only the `aws-s3` module happens to expose a `v1/bucket`, so it resolves there and locks. Apply that same manifest to cluster B, a fresh cluster with no existing lock, and if two different modules both happen to ship a `v1/bucket` there, admission just fails outright with an ambiguity error. Same YAML, different outcome, purely because Form 2's resolution genuinely depends on cluster state at the moment of first apply. Form 3 has no such dependency. The module name is already sitting right there in the string, so there's no resolution step to run at all, and it behaves identically on every cluster from the first apply onward.

### Upgrading to a new API line

This is deliberately manual, not automatic. Even once a v2 line exists and is installed, every app stays locked to v1 forever unless someone explicitly edits `type:`, for example bumping `aws-s3/v1/bucket` to `aws-s3/v2/bucket`. When that edit happens, the webhook doesn't rerun any ambiguity selector. It derives the new triple straight from the Form 3 string, checks that module and name haven't changed (only apiVersion moved), and updates just that one field in the existing lock. Any other spec change that doesn't touch `type:` keeps resolving off the old lock exactly as before.

### Resetting a lock

An operator can directly delete the `ComponentDefinitionLock` entry from the `ApplicationRevision`. That returns the component to its unbound, first-time-submission state. On the next admission, if it's Form 2, the selector runs fresh against whatever's currently on the cluster and binds to wherever that lands, still subject to the same ambiguity check as before. This is explicitly framed as a deliberate operator action with real contract implications, not routine maintenance, because you're choosing to let the binding get re-derived from current cluster state instead of staying pinned to what it was.

### Lock staleness: the failure mode

Say the module backing a locked definition gets uninstalled entirely. On the next reapply, the webhook tries a direct GET on the stored triple, and it's gone. It does not fall back to some other definition with the same name, even if one exists under a different module or as a legacy definition. That's deliberate: silently rebinding to a different definition after an uninstall would be exactly the kind of silent contract swap this whole locking mechanism exists to prevent. Instead you get a hard error naming the missing definition and pointing at the fix. Recovery is manual:

1. Find the ApplicationRevision name: `kubectl get application <app-name> -o jsonpath='{.status.latestRevision.name}'`
2. Remove that specific lock entry by index: `kubectl patch applicationrevision <revision-name> --type=json -p='[{"op":"remove","path":"/spec/definitionLocks/<i>"}]'`
3. Update `type:` to the replacement's Form 3 name and reapply. The component is now unbound, so the webhook treats it as a first admission and writes a brand-new lock. Using Form 3 here means the new binding is deterministic from that very first apply, with no risk of hitting the same ambiguity problem Form 2 could hit.

### v1/v2 coexistence

Adding a v2 line to a module doesn't touch v1 at all. Both CRs, `aws-s3-v1-bucket` and `aws-s3-v2-bucket`, just sit there installed side by side. Every app already locked to v1 stays on v1 indefinitely. Neither the addon upgrade nor unrelated spec edits move it. The only way off v1 is the explicit `type:` edit described above. The v1 line keeps working until someone deliberately deprecates and removes it later.

---

## Q4. Which "definitions" does the module/apiVersion model apply to: built-in KubeVela defs or addon defs?

That confusion is fair, the KEP doesn't spell this out until much later in the doc. Let me untangle it.

### It's the same CRD either way

There's no separate "built-in definition" type and "addon definition" type in KubeVela. Both are just instances of ComponentDefinition, TraitDefinition, WorkflowStepDefinition, or PolicyDefinition. Same CRDs, same schema, same admission path. The only difference has ever been where the YAML came from: bundled with vela-core at install time, or applied by an addon's install logic.

`spec.module` and `spec.apiVersion` are just two new optional fields bolted onto that existing spec. Since they're fields on the CRD itself, not something scoped to "addon-sourced objects only," any ComponentDefinition anywhere, built-in, addon-delivered, or even something you `kubectl apply` by hand, can carry them or not. The model doesn't care where the object came from. It only cares whether those two fields are populated.

### Three ways a definition actually gets these fields

1. The addon controller sets them automatically. This is the path the KEP is mostly written around. If an addon adopts the new `modules/` plus `_version.cue` layout from KEP-2.13, the addon controller stamps `spec.module` and `spec.apiVersion` onto every definition it installs from that layout. This is what "typically set by the addon controller" means.
2. A platform engineer can set them by hand on anything they author themselves. You don't need an addon in the loop at all. Write a ComponentDefinition YAML, set `spec.module: my-internal-tools`, `spec.apiVersion: v1`, and `kubectl apply` it directly.
3. KubeVela's own built-ins get folded in as a special case, and this is the direct answer to your question. Later in the KEP there's a "Built-in `vela` Module" section. KubeVela reserves a module name, literally `vela`, for its own shipped definitions: `webservice` becomes `vela-v1-webservice`, `apply-once` becomes `vela-v1-apply-once`, and so on. These get installed by the KubeVela controller itself at startup, not by the addon controller, since there's no Addon CR wrapping core KubeVela. But the naming convention, the labels, the versioning behavior, all of it matches any addon-delivered module exactly. `vela` is just reserved so no addon author can name their own module that.

### What stays untouched

Anything missing either field, which today is basically everything, every current addon's `definitions/` output and every current built-in, just stays "legacy." Resolved by exact name, exactly like now. Nothing forces migration. A ComponentDefinition doesn't become part of this system until someone, the addon controller or a human, deliberately sets both fields on it.

### Why this exists at all, restated plainly

The actual goal isn't "addons vs built-ins." It's giving any definition, no matter where it came from, a real identity beyond just its bare name. Today `bucket` is `bucket`, full stop, whether it's a built-in or shipped by three different addons that all happen to use that name. There's no way to tell them apart or let more than one coexist. `{module}/{apiVersion}/{name}` fixes that by making the identity explicit and three-part, so an app's `type:` field can point at exactly one specific thing, and multiple sources (the built-in `vela` module, addon A, addon B, a hand-authored one) can all define something called `bucket` without colliding.

---

## Q5. When do you use Form 1 vs Form 2?

Form 1 (`type: bucket`) isn't really a choice you make, it's what you're stuck with when a definition never opted into the module system at all. Use it when the definition has no `spec.module`/`spec.apiVersion` set, which today means every existing addon and every existing built-in. If someone later versions a definition with that same bare name, Form 1 for that name gets rejected outright. You don't get to keep using it.

Form 2 (`type: v1/bucket`) is for when you're working with a module-backed definition, you know which API version you want, but you don't care to spell out which module provides it. The webhook looks it up once via a label selector on `(apiVersion, name)`, locks onto whichever module matches, and reuses that lock forever after. Good for interactive use or exploring a cluster where you're confident there's exactly one match. Not good for anything landing in git or GitOps, since a fresh cluster with no existing lock has to run that selector fresh, and if two modules both happen to expose a `v1/bucket`, admission fails with an ambiguity error on a manifest that worked fine somewhere else.

The KEP's own guidance table boils it down like this: production manifests, GitOps repos, and automated pipelines should use Form 3. Form 2 is for "I know the version, I don't need to pin the module." Form 1 is strictly for legacy, non-module definitions, hand-authored things that were never brought into this system. And for a brand-new module-backed definition, Form 1 isn't even on the table, you're required to use Form 2 or Form 3.

---

## Q6. Explain "Recommended Usage": the contract policy flag and the two-step API line migration.

This section is mostly a rules-of-thumb recap of things we've already covered, packaged as day-to-day guidance for people writing manifests. Going quick on the overlap, spending more time on the two things that are genuinely new here.

### The parts that just restate earlier answers

Form 3 for anything in git, GitOps, or CI/CD, because it's the only form with zero cluster-state dependency, same as covered in Q1 and Q5. Form 1 only for definitions that never got `spec.module` set, also already covered: if a definition is versioned, Form 1 gets rejected outright, it's not a style choice. And "don't rely on implicit re-binding" just restates the definition lock behavior from Q3. Nothing, not a new API line, not an unrelated spec edit, moves the lock. Only an explicit `type:` change to Form 3 can move `apiVersion`, and `module`/`name` can never move at all without replacing the reference entirely.

### What's actually new: the contract policy flag

`--api-line-contract-policy=warn|reject` is a cluster-level webhook setting that puts real enforcement behind "treat API lines as stable contracts." Without it, "don't break the parameter contract within a line" is just a convention people are trusted to follow. With `warn` or `reject` turned on, the webhook runs a structural comparison of the `parameter:` schema between the old and new version of a definition that keeps the same `apiVersion`, and flags obvious breakage: a required field disappearing, a type getting narrowed, that kind of thing.

Worth keeping the limits straight: this check is schema-only and static. It compares the shape of the parameter block, nothing else. It has no visibility into template logic changes, output schema changes, or changes to auxiliary resources like Compositions, XRDs, or ResourceGraphDefinitions. A module author could pass this check clean and still ship a behavioral breaking change by editing the template body or the backing Composition. So the flag is a useful tripwire for the most mechanical class of breakage, not a substitute for the author being careful. That responsibility stays with whoever owns the module.

### What's actually new: the two-step migration

Moving a component from v1 to v2 is deliberately split into two separate, independently reviewable changes instead of one edit.

Step 1: if you're currently on Form 2 (`type: v1/bucket`), first change it to the fully qualified Form 3 for the version you're already on, `type: aws-s3/v1/bucket`. Nothing about behavior changes here. You're still on v1, you're just making the module explicit. The lock gets written as `{module: aws-s3, apiVersion: v1, name: bucket}`. If you were already on Form 3, skip this step, you're already there.

Step 2, as its own separate change: bump the version segment, `type: aws-s3/v2/bucket`. Module and name match what's already in the lock, only `apiVersion` differs, so this is accepted as a valid migration and the lock updates to `{module: aws-s3, apiVersion: v2, name: bucket}`.

Why bother splitting these into two PRs instead of one? It makes each change auditable on its own terms. Step 1's diff should show nothing behavior-relevant changing, just the type string becoming explicit, so a reviewer can approve it without much thought. Step 2's diff is then purely "this component is intentionally moving to v2," with no other noise mixed in. Do both in one shot, and a reviewer looking at a bare `type: v1/bucket` turning into `type: aws-s3/v2/bucket` has to untangle "was the module always aws-s3, or did this also just get pinned for the first time" at the same time as "is this version bump intentional." Splitting it removes that ambiguity. And through all of this, the old v1 line just keeps running for anyone who hasn't migrated yet. This migration is opt-in per component, not a flag day for the whole cluster.

---

## Q7. Real-world worked example: Form 2 vs Form 3.

Let's build one continuous story instead of disconnected examples, since that's closer to how this would actually play out on a real platform team.

### Setup

Platform team publishes an addon named `aws-s3`. It's been upgraded to use the new `modules/` plus `_version.cue` layout. On install, the addon controller installs one definition on the cluster:

```
ComponentDefinition: aws-s3-v1-bucket
  labels:
    definition.oam.dev/module: aws-s3
    definition.oam.dev/api-version: v1
    definition.oam.dev/name: bucket
```

### Scenario A: an engineer exploring on a sandbox cluster (Form 2)

A dev on the checkout-service team is playing around on a personal k3d sandbox where only the `aws-s3` addon is installed. They don't want to type the full module name while iterating, so they write:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: checkout-bucket-test
spec:
  components:
    - name: my-bucket
      type: v1/bucket
```

`vela up`. On admission, the webhook has no lock for this component yet, so it runs the label selector: `definition.oam.dev/api-version=v1, definition.oam.dev/name=bucket`. On this sandbox, exactly one definition matches, `aws-s3-v1-bucket`. Admission succeeds, and the webhook writes a lock: `{module: aws-s3, apiVersion: v1, name: bucket}`. The app runs fine. This is exactly the "convenience for interactive and exploratory use" the KEP describes.

### Scenario B: the same YAML, now on the shared staging cluster (why Form 2 breaks)

Now suppose the platform team also runs a second addon on shared clusters, `crossplane-community`, which happens to ship its own generic bucket capability, also versioned `v1`, also named `bucket`. Nobody planned this collision, it's just two different vendors both calling their thing "bucket." Both definitions carry the exact same `(apiVersion, name)` label pair.

The checkout-service dev takes the exact same YAML from Scenario A (`type: v1/bucket`) and applies it fresh to staging, where there's no existing lock. Now the webhook's selector for `(api-version=v1, name=bucket)` returns two results: `aws-s3-v1-bucket` and `crossplane-community-v1-bucket`. Per the ambiguity rule, admission is rejected outright:

```
Error: ambiguous reference "v1/bucket": matches aws-s3-v1-bucket
and crossplane-community-v1-bucket. Use module/apiVersion/name (Form 3)
to disambiguate.
```

Same YAML, same intent, different outcome, purely because the cluster's module population differs. This is the concrete failure mode behind "Form 2 resolves against cluster state at first admission and is not reproducible across environments."

### Scenario C: doing it right for the PR that ships to production (Form 3)

For the actual manifest that goes into the checkout-service repo and gets deployed by ArgoCD to dev, staging, and prod, the platform team's convention requires:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: checkout-bucket
spec:
  components:
    - name: my-bucket
      type: aws-s3/v1/bucket
```

Now there's no selector step at all. On any cluster, whether it has one bucket-shaped module or five, the webhook derives the CR name directly from the string, `aws-s3-v1-bucket`, does a plain GET, and either it exists or it doesn't. No ambiguity is possible, because the module is already named. ArgoCD can sync this exact same file to dev, staging, and prod, and it resolves identically every time. This is why the KEP's single most emphasized rule is "Form 3 for anything in version control or GitOps."

### Tying it back

The dev's workflow here naturally mirrors the two-step migration pattern from earlier, just applied to going from exploration to production instead of v1-to-v2: prototype fast with Form 2 on a sandbox, then when it's time to commit the manifest for real, make the module explicit with Form 3 before it ever reaches a shared or automated environment. That's really the whole "when to use Form 2 vs Form 3" distinction in one motion: Form 2 while you're the only one touching the cluster and you're confident about what's installed, Form 3 the moment the manifest leaves your hands.

---

## Q8. Is an addon just installing definitions for an application to use?

Close, but it's missing a layer. Let me correct the picture.

For exactly the slice of the KEP we've been through so far (identity, naming, Form 1/2/3, the lock), yes, that's entirely about definitions and how an app's `type:` field points at one. Nothing wrong there.

But zoom out one level and an addon isn't just a definition installer. Per its full lifecycle, which is KEP-2.13's territory (this KEP just depends on it), an addon actually ships three layers:

1. Infrastructure: an owned Application in `vela-system` running the actual operator and CRDs, say the Crossplane provider for AWS.
2. Auxiliary resources: for module-backed lines, things like Crossplane XRDs and Compositions that back a definition's behavior.
3. Definitions: the ComponentDefinition/TraitDefinition objects, applied last, only once the layers below are healthy.

Definitions are the final, user-facing layer of what an addon ships, not the whole of it.

Tying it to the `aws-s3` example from before: the addon doesn't just drop `aws-s3-v1-bucket` onto the cluster and call it done. It also installs the Crossplane provider and operator, plus the XRD and Composition that back that bucket type. Only once that infrastructure is up and healthy does the definition actually get applied. If it skipped straight to the definition with nothing behind it, an app referencing `aws-s3/v1/bucket` would render a Claim that no operator or Composition can actually fulfill.

So the corrected model: an addon ships infrastructure, auxiliary resources, and definitions. An Application only ever touches the definitions layer, through `type:`. This particular KEP, 2.20, only concerns itself with that last layer: how it's identified, named, and resolved. The rest of the addon lifecycle, the infrastructure and auxiliary parts, belongs to KEP-2.13.

---

## Q9. Where does the definition lock actually get written? Give an example.

`ApplicationRevision` isn't new. It's the same CR that already gets auto-created every time you publish a new version of an Application's spec, the thing you already use for rollback. This KEP just bolts one new field onto its `spec`: `definitionLocks`.

Picking up the `checkout-bucket-test` Application from Q7, once it gets admitted with `type: v1/bucket` resolving to `aws-s3-v1-bucket`, KubeVela will have created something like this:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: ApplicationRevision
metadata:
  name: checkout-bucket-test-v1
  namespace: default
  labels:
    app.oam.dev/name: checkout-bucket-test
spec:
  application:
    metadata:
      name: checkout-bucket-test
    spec:
      components:
        - name: my-bucket
          type: v1/bucket   # exactly what the user wrote, untouched
  definitionLocks:
    - componentName: my-bucket
      resolvedDefinition:
        module: aws-s3
        apiVersion: v1
        type: bucket
        fullyQualifiedName: aws-s3-v1-bucket
```

Two things worth pointing at directly.

The `spec.application` block is just the usual frozen snapshot of the Application's spec at that revision, same as today, nothing new. Notice `type: v1/bucket` is still sitting there exactly as the user typed it. The lock doesn't rewrite the user's YAML into some normalized form. `definitionLocks` is a sibling field next to it, holding the resolved result separately.

`definitionLocks` is the new part: one entry per component, keyed by `componentName`, carrying the resolved `{module, apiVersion, type, fullyQualifiedName}`. That's the actual thing every future admission reads back, not the `type:` string in the spec.

On a real cluster you'd go find this with:

```bash
kubectl get application checkout-bucket-test -o jsonpath='{.status.latestRevision.name}'
kubectl get applicationrevision checkout-bucket-test-v1 -o yaml
```

In day-to-day practice, though, you'd rarely dig into `ApplicationRevision` directly just to check a binding. The live `Application` object itself carries a read-only mirror at `.status.services[i].resolvedDefinition`, so `kubectl get application checkout-bucket-test -o yaml` and looking under `status.services` shows you the same `{module, apiVersion, type, fullyQualifiedName}` without having to go find the revision object at all. That status field is just a projection, though, with no binding authority. The `ApplicationRevision` entry is still the actual source of truth.

---
