# AWS EKS Pod Identity connect: the runbook, explained

A walkthrough of the "AWS EKS Pod Identity Connect: Full Test Runbook" (epic GWCP-100435),
section by section, with each step explained rather than just listed. Where the runbook and
the current branch disagree, the disagreement is called out.

Reading context: the runbook was executed on branch `feat/spokecluster-connect-phase1`, the
prototype. This document was written against `feat/cluster-kep-infrastructure`, the
productionized version of the same work. Code references below are to the latter.

---

## 1. The frontmatter, and what "verified" buys you

The document is tagged `status: verified`, epic GWCP-100435, created 2026-07-03. That single
field changes how you should read everything below it. This is not a design proposal or a plan
someone hoped would work. Someone ran it, and the SpokeCluster came up `Connected` against
real EKS.

The practical value is that every command in it has already been executed once. Where a command
is wrong, it is wrong because AWS or the chart changed since July, not because it was written
from imagination. That is a much better starting position than a fresh plan.

One caveat the document does not state loudly enough: some prototype behavior was deliberately
trimmed on the way to the productionized branch. Each place that matters is flagged below.

---

## 2. The two headline bugs

The author puts these at the top rather than burying them in the chronology, which is the right
call, because they are the only two things in the document that were not just operator error.

### Bug 1 lived in the prototype code

The AWS provider mints an EKS bearer token by presigning an STS `GetCallerIdentity` request.
The AWS SDK v2 presign path does not add an `X-Amz-Expires` query parameter. EKS requires one
and rejects any token without it, with a flat `401 Unauthorized` that tells you nothing about
why.

What makes this bug interesting is not the fix but the blind spot. Unit tests used a fake
presigner, so no signing happened. The k3d path uses static kubeconfigs, so no token was ever
minted. The only thing on earth that rejects a missing `X-Amz-Expires` is a real EKS token
validator, and nothing in CI is one. A whole test suite can be green while the feature is
completely broken in its only real deployment target.

Status on this branch: fixed. See `pkg/spokecluster/credential/aws_token.go:46-94`.

### Bug 2 was environmental, not code

The cluster-gateway APIService shipped with its `caBundle` set to `Cg==`, which is base64 for a
single newline. The Helm chart writes that as a placeholder and relies on a post-install Job to
overwrite it with the real CA. Installing with `admissionWebhooks.enabled=false` disables that
Job, so the placeholder survives, and the kube-apiserver cannot verify the gateway's TLS. Every
proxied request then dies with:

```
unable to load root certificates: unable to parse bytes as PEM block
```

Status on this branch: partially hardened. `charts/vela-core/templates/cluster-gateway/cluster-gateway.yaml:169-179`
now reads the existing APIService on upgrade and keeps a caBundle that is not the placeholder,
so a working install no longer gets reset. On a fresh install with webhooks disabled there is
nothing to preserve, so you still land on `Cg==`. Step A9 is still required.

---

## 3. The environment table

Two EKS clusters in one AWS account, both v1.35.5, in us-west-2. Hub is
`atmos-scratch-rmtest1`, spoke is `atmos-scratch-rmtest2`.

The one field worth reading carefully is the spoke's authentication mode:
`API_AND_CONFIG_MAP`. EKS access entries only exist in `API` or `API_AND_CONFIG_MAP` mode. If a
spoke is still on `CONFIG_MAP`, step A7 cannot work at all and you would have to edit the
`aws-auth` ConfigMap by hand instead. Check this before anything else, because discovering it
late means redoing your IAM plan.

The hub's mode is `CONFIG_MAP` and that is fine, because nothing in this flow creates an access
entry on the hub.

Both clusters being in the same account means no genuine cross-account trust. The author notes
that the model is identical anyway, because the scoped role trusts the hub base role by ARN and
is gated by an externalId. Moving to two accounts changes the ARNs, not the shape.

---

## 4. Devcontainer hygiene

Two `unset` commands that look like trivia and are not.

`unset AWS_PROFILE` matters because the container ships `AWS_PROFILE=""`. An empty string is not
the same as unset. The SDK sees a profile is requested, goes looking for it, and the exec
credential helper breaks in a way whose error message does not mention profiles.

`unset KUBECONFIG` matters because the env file exports a macOS host path that does not exist
inside the container. You get "file not found" on a path you never chose.

Both are the kind of failure that costs twenty minutes because the symptom points nowhere near
the cause.

---

## 5. Part A: the clean path

This is the runbook rewritten with both fixes baked in. Eleven steps.

### A1: source credentials and confirm identity

```bash
source ~/.dev/aws-envs/scratch2.env
unset AWS_PROFILE
aws sts get-caller-identity
aws eks list-clusters --region us-west-2 | grep rmtest
```

The point of `get-caller-identity` is not ceremony. Everything downstream assumes a specific
account number, and IAM errors are much harder to read than a wrong account number printed on
screen. `list-clusters` confirms both clusters exist before you spend an hour building an image
for them.

### A2: build kubeconfigs for both clusters

Two separate kubeconfig files at `/tmp/rmtest1.kubeconfig` and `/tmp/rmtest2.kubeconfig`, with
aliases. Separate files rather than merged contexts, which makes it much harder to run a
destructive command against the wrong cluster by forgetting to switch context.

This is also where you check the spoke's authentication mode, for the reason described above.

You only ever need the spoke kubeconfig for verification. The connect flow itself never uses it,
because the whole point is that the hub reaches the spoke through AWS identity rather than a
stored kubeconfig.

### A3: clean the existing atmos and Flux managed kubevela

The hub was not a blank cluster. It ran the `ccs-atmos-kubevela` distribution reconciled by
Flux, alongside crossplane, argo and atlas.

Flux is the complication. If you simply `helm uninstall vela-core`, Flux notices the drift and
puts it back. So the loop suspends about fourteen HelmReleases first, and only then uninstalls
the three vela controllers. The order is not optional.

The author notes these were scratch clusters slated for teardown, so the restore path (flip
`suspend` back to false) was optional. On any cluster you care about, that restore is the thing
you plan before you start.

### A4: build the image and push to ECR

EKS cannot pull from your local Docker daemon, so the image has to live somewhere the nodes can
reach.

Two cross-compiles, both `GOOS=linux GOARCH=amd64`, because the devcontainer is arm64 and the
EKS nodes are not. Two binaries, `manager` from `cmd/core/main.go` and `cluster-manager` from
`cmd/cluster-core/main.go`, because vela-core and vela-cluster-core are separate processes in
the same image. `CGO_ENABLED=0` for static binaries that run on alpine.

Then a minimal Dockerfile with `--platform=linux/amd64` pinned again at the FROM line, an ECR
repo, a docker login using an ECR password that expires, and a push.

If you skip the platform pin in either place you get an image that pulls fine and then
crash-loops with `exec format error`.

### A5: create the IAM roles

This is the conceptual heart of the whole exercise, and it is worth slowing down.

There are two roles, and the split is deliberate.

The **hub base role** (`oam-sc-hub-base`) is what the controller pod becomes. Its trust policy
names the principal `pods.eks.amazonaws.com`, which is the Pod Identity service, and allows
`sts:AssumeRole` and `sts:TagSession`. Its permission policy allows exactly one thing: assuming
the scoped role. It has no EKS permissions of its own.

The **per-cluster scoped role** (`oam-sc-rmtest2-scoped`) is what actually talks to the spoke.
Its trust policy names the hub base role as principal, gated by an externalId condition. Its
permission policy allows `eks:DescribeCluster` on one cluster ARN and nothing else.

The reason for two roles instead of one: the hub controller manages many spokes, and you do not
want one credential that can describe all of them. Adding a spoke means adding a scoped role and
one line to the base role's assume list. A compromised spoke role reaches exactly one cluster.

The externalId is the part that catches people. EKS Pod Identity generates it as
`<region>/<hubAccount>/<hubCluster>/<namespace>/<serviceAccount>`, so in this case:

```
us-west-2/776719623202/atmos-scratch-rmtest1/vela-system/vela-core
```

You do not choose this string. You transcribe it, and if the last segment is wrong the
AssumeRole fails.

Which brings up the warning the author boxed off: whether that last segment is `vela-core` or
`vela-core-cluster-core` depends entirely on whether you set
`clusterCore.aws.serviceAccountRoleArn` in the chart. Set it, and the chart creates a dedicated
service account. Leave it unset, and the cluster-core pod runs as the shared `vela-core` service
account. This runbook left it unset.

In our code, all of this lands in one function. `defaultAWSClientFactory`
(`pkg/spokecluster/credential/aws.go:114`) calls `awsconfig.LoadDefaultConfig`, which is where
Pod Identity silently enters through an injected env var, then `stscreds.NewAssumeRoleProvider`
with `o.ExternalID` set from the CR. Nothing in the code validates the externalId. It cannot.
Only AWS knows whether it matches.

### A6: Pod Identity agent and association

Two separate things that are easy to conflate.

The **agent** is an EKS addon that runs on the hub and injects credentials into pods. It is
cluster-wide, installed once. On this hub it was already `ACTIVE`.

The **association** is a mapping from one Kubernetes service account to one IAM role. That is
what says "pods running as `vela-system/vela-core` get the hub base role."

Without the agent, associations do nothing. Without an association, the agent has nothing to
inject.

### A7: access entry on the spoke

Everything so far has been AWS-side identity. This step is the bridge into Kubernetes RBAC on
the spoke.

`create-access-entry` registers the scoped role's ARN as a principal the spoke recognizes.
`associate-access-policy` then grants it a policy. The runbook used
`AmazonEKSClusterAdminPolicy` so that read-through and writes both work, while noting
`AmazonEKSViewPolicy` is enough for connect alone, since connect only probes and discovers.

Without this step you get a token that AWS accepts and the spoke's authorizer refuses. That is a
403, not a 401, which is a useful distinction when debugging.

### A8: install vela-core and vela-cluster-core on the hub

One helm install with several flags, and the interesting ones are all there to dodge a hurdle
discovered later.

`featureGates.enableClusterInfrastructure=true` turns on the SpokeCluster controller, webhook,
RBAC and the separate cluster-core pod. Worth knowing that the chart defaults this to `false`
(`charts/vela-core/values.yaml:173`) while the Go feature gate defaults to `true`
(`pkg/features/controller_features.go:184`). The chart wins for a Helm install, so the flag is
not optional.

`admissionWebhooks.enabled=false` is what causes Bug 2. The author's own advice in the box above
the command is to leave it `true` so the cert Job runs. The command below the box then sets it
to `false` anyway, because that is what was actually executed. Read the box, not the command.

`multicluster.clusterGateway.direct=false` avoids Hurdle 5. Still needed on this branch:
`charts/vela-core/values.yaml:229` defaults it to `true`.

Then three pods should be running: vela-core, vela-core-cluster-core, and
vela-core-cluster-gateway. The middle one is the one you care about.

### A9: fix the cluster-gateway caBundle

Read the placeholder, pull the real CA out of the gateway's TLS secret under the key `ca`, patch
it into the APIService.

```bash
CA=$(kubectl get secret vela-core-cluster-gateway-tls-v2 -n vela-system -o jsonpath='{.data.ca}')
kubectl patch apiservice v1alpha1.cluster.core.oam.dev --type=merge \
  -p "{\"spec\":{\"caBundle\":\"${CA}\"}}"
```

Only needed when the cert Job did not run. On a fresh install with webhooks disabled, it did not
run.

### A10: restart cluster-core, then apply the SpokeCluster

The restart is not superstition. A Pod Identity association only affects pods created after it
exists, so the pod that was already running has no credentials. The verification command greps
the pod env for `AWS_CONTAINER_CREDENTIALS_FULL_URI`, and its presence is the proof that Pod
Identity took.

Then the CR itself, which is short. Mode connect, credential type aws, authMode podIdentity,
plus cluster name, region, role ARN and externalId. Four AWS facts and nothing else. Compare
that to the volume of IAM setup behind it, and you can see what the CRD is buying: the operator
writes six lines, and the platform team owns the roles.

### A11: verify

Four conditions, all True, in the order the reconcile writes them: `CredentialValid`,
`Registered`, `Connected`, `InfoSynced`. Because `reconcileConnect`
(`pkg/controller/core.oam.dev/v1beta1/spokecluster/spokecluster_controller.go:109`) stops at the
first hard failure, wherever the True values stop is exactly where the problem is. That property
is worth internalizing, since it turns a vague "it does not work" into a specific layer.

Then a raw read-through to the spoke's namespaces via the gateway proxy, and the CLI commands.

**The expected output here will not match on this branch.** It shows `NODES=5`, `PLATFORM=eks`,
`REGION=us-west-2`. The current `discover`
(`pkg/controller/core.oam.dev/v1beta1/spokecluster/discovery.go:44`) sets only
`KubernetesVersion`, `APIServerEndpoint` and `LatencyMillis`, with an explicit comment deferring
node count, platform and region to the discovery slice, GWCP-102133. So expect version and
`Connected` with the rest blank. Not a regression.

---

## 6. Part B: the hurdles, in the order they were hit

Part A is the path you wish you had taken. Part B is what actually happened. Read it as a
debugging log.

**Hurdle 0** was a wrong credentials path plus a KUBECONFIG pointing at a macOS directory.
Fifteen minutes, no insight, pure environment.

**Hurdle 1** was a scare rather than a problem. The author's notes warned that cluster-gateway
breaks on Kubernetes 1.35, and both clusters were v1.35.5. This looked like a hard blocker at the
outset. It turned out to be a misdiagnosis of what later became Hurdle 6: cluster-gateway
`v1.9.0-alpha.2` is fine on 1.35 once its caBundle is valid. Worth noting as an example of a
remembered symptom sending you down the wrong path.

**Hurdle 2** was the hub being a real Flux-managed cluster rather than a clean one, which is what
A3 exists to handle.

**Hurdle 3** was image distribution, which A4 handles.

**Hurdle 4** is a tooling artifact. `helm install --wait` blocks until pods are Ready, which
exceeds the shell tool's two minute timeout, so the command reports failure while the release
deployed fine. The fix is to check `helm list -a` afterwards rather than trusting the exit code,
or to drop `--wait` and poll.

**Hurdle 5** was vela-core crash-looping on `/cluster-gateway-tls-cert/ca: no such file or
directory`. Root cause is an interaction between two settings: `direct=true` (the chart default)
makes vela-core talk to the gateway directly and mount its TLS cert, but
`admissionWebhooks.enabled=false` means nothing ever created that cert. Setting `direct=false`
routes vela-core through the apiserver instead and the mount is no longer needed.

**Hurdle 5b** was the service account name in the externalId, described under A5. The
verification command is one line: read `spec.template.spec.serviceAccountName` off the
cluster-core deployment and use whatever it says.

**Hurdle 5c** was the Pod Identity restart, described under A10.

**Hurdle 6** is the most instructive entry in the document, because of how it was isolated rather
than what it turned out to be.

The symptom was `Connected=False (ProbeFailed)` with a PEM parse error. The AWS conditions were
both True, so the credential path was fine. The debugging went:

1. Check the materialized gateway Secret's `ca.crt`. It was valid PEM, so the provider's base64
   decode was correct. That eliminated the code the author had just written, which is the right
   thing to eliminate first when you are the one who wrote it.
2. Test the gateway proxy against the local hub cluster. That path involves no SpokeCluster and
   no AWS at all. It failed with the identical PEM error. One command, and the entire AWS half of
   the system is ruled out.
3. A dead end: bumping the gateway image to `latest`, which crash-looped and left
   `MissingEndpoints`. Reverted.
4. Check the APIService caBundle directly. `Cg==`.

The general lesson is step 2. When a request crosses several components, find the shortest path
through the same machinery that excludes the component you suspect. If the short path fails too,
your suspect is innocent.

**Hurdle 7** is Bug 1, and the debugging is worth reading for the technique.

After the TLS fix the probe returned 401. The author decoded the minted token (it is just a
base64url-encoded URL behind a `k8s-aws-v1.` prefix) and replayed the presigned URL with curl,
adding the `x-k8s-aws-id` header. That is precisely what EKS does internally. The response
contained the correct assumed-role ARN, which proved AssumeRole, DescribeCluster and the role
scoping all worked.

So the identity was right and the token was still refused. That narrows it to the token's form
rather than its content. Decoding the query parameters showed `X-Amz-Date` present,
`X-Amz-SignedHeaders` present, `X-Amz-Algorithm` present, and `X-Amz-Expires` missing.

Being able to replay a credential against the thing that validates it is the technique to steal
here. It converts "the server said no" into "here is the exact field that is absent."

---

## 7. Part C: cleanup

Six steps in a specific order, and the order is enforced by AWS dependencies.

Kubernetes objects first. Deleting the SpokeCluster while the controller is still running
matters, because the finalizer runs `DetachCluster` and removes the gateway Secret. Delete the
Helm release first and the finalizer has no controller to run it, so you get a stuck object
needing a manual finalizer patch.

Pod Identity association next, looked up by service account name rather than hardcoded, since
the association ID is generated.

IAM roles after that, and inline policies must be deleted before the role. AWS refuses to delete
a role that still has policies attached.

Then the access entry on the spoke, then the ECR repo with `--force` because it has images in it.

Finally the optional Flux resume, flipping the same fourteen HelmReleases back to
`suspend: false`.

The verification block at the end is the part people skip. Four commands that each assert
emptiness. IAM roles left behind are the ones that matter, since they are the ones that outlive
the clusters and end up in an audit.

---

## 8. Appendix A: the manifest

The same CR as A10, repeated for copy-paste. Labels `provider: aws` and `region: us-west-2` are
decorative and do nothing functional.

Note `authMode: podIdentity` with `irsa` as the alternative. Both resolve through the same
`LoadDefaultConfig` call in the provider, because both work by making the ambient AWS identity
correct before any of our code runs. The CRD field is documentation of intent more than a
behavioral switch on the hub side.

---

## 9. Appendix B: the fix

Three pieces. A `setExpiresMiddleware` type that writes `X-Amz-Expires` into the request query. A
`withPresignExpires` helper that registers it on the Build step. The wiring into
`PresignGetCallerIdentity` alongside the existing `x-k8s-aws-id` header setter.

The Build step placement is the whole trick. Smithy runs Initialize, Serialize, Build, Finalize,
Deserialize. The presign signer runs in Finalize. Registering on Build means the parameter is in
the URL before signing, so the signature covers it. Register it in Finalize and the signature
would not cover the parameter, and EKS would reject the token for signature mismatch instead of
missing expiry. Same failure, different reason, equally opaque.

All of this is present on this branch at `pkg/spokecluster/credential/aws_token.go:51-72`, wired
at line 94.

**One thing the appendix recommends that was never done.** The author writes that this argues for
"adding a unit assertion that the minted URL contains `X-Amz-Expires`." No such test exists.
`grep` finds no reference to it in any test file, and `fakePresigner`
(`pkg/spokecluster/credential/aws_token_test.go:36`) discards the `PresignOptions` argument
entirely, so the middleware never executes under test.

Closing that gap means constructing a real `sts.NewPresignClient` with static dummy credentials
and asserting on the resulting query string, rather than stubbing. It is a genuine piece of work,
not a one-liner, and it is the single highest-value thing to do before the AWS run rather than
after. A green suite that cannot detect the bug it was written in response to is worth fixing
while the reason is fresh.

---

## 10. Appendix C: how to inspect a token

A Python snippet that strips the `k8s-aws-v1.` prefix, base64url-decodes with padding restored,
and prints the query parameters that matter. Then a curl replay showing the resolved ARN.

Keep this. When an EKS token fails, these two commands tell you whether the problem is identity
(wrong ARN comes back) or form (a parameter is missing). Those are completely different fixes,
and the 401 alone does not distinguish them.

The code has a matching helper in non-test code deliberately: `decodeEKSTokenURL`
(`pkg/spokecluster/credential/aws_token.go:115`), with a comment explaining it lives outside
`_test.go` so the generator and its tests share one definition of the format.

---

## Where this leaves us

Bug 1 is fixed on this branch. Bug 2 is half fixed, covering upgrades but not fresh installs.
Hurdles 5, 5b and 6 are all still live and will happen again unless the flags in A8 and the patch
in A9 are used. The discovery output will be thinner than A11 shows, because that work moved to
GWCP-102133. And the regression test the document asked for was never written.

For the real run, the first thing needed is AWS access. The credentials, the IAM roles and both
rmtest clusters belong to a different engineer's scratch setup, and Part C removed the roles, the
association, the access entry and the ECR repo. Whether the clusters themselves still exist is
not recorded.
