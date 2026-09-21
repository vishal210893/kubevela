# SpokeCluster on real EKS, with cluster-core running in your IDE

A working end to end setup for testing the SpokeCluster connect flow against two real EKS
clusters, without deploying any KubeVela controller. Only cluster-gateway runs in the cluster.
The SpokeCluster controller runs on your laptop under a debugger.

Verified 2026-08-04 on `atmos-scratch-cghub` (hub) and `atmos-scratch-cgspoke1` (spoke), account
`776719623202`, us-west-2. Final result: `Connected`, v1.35.6-eks, 3 nodes, 24 CPU, 186.8Gi,
321ms latency.

---

## What this builds

```
your laptop                          hub cluster                 spoke cluster
-----------                          -----------                 -------------
vela-cluster-core (IDE debugger)
  |
  | 1. AssumeRole + eks:DescribeCluster + mint EKS token
  |    (uses YOUR local AWS credentials)
  +--> AWS STS / EKS API
  |
  | 2. write gateway Secret
  +------------------------------> Secret vela-system/cgspoke1
  |
  | 3. probe + discover
  +------------------------------> kube-apiserver
                                     |
                                     +-> APIService v1alpha1.cluster.core.oam.dev
                                          |
                                          +-> cluster-gateway pod
                                               |
                                               +--------------------> EKS API (spoke)
```

Three facts that explain most of the setup work:

The controller runs locally, so **Pod Identity does not apply**. `awsconfig.LoadDefaultConfig`
in `pkg/spokecluster/credential/aws.go:115` picks up whatever AWS credentials your shell has. In
a pod it would find Pod Identity. On your laptop it finds your session.

The probe and discovery do **not** go from your laptop to the spoke. They go through the hub's
cluster-gateway pod (`probe.go:57`, `discovery.go:52`). That is why cluster-gateway must be
installed even though no other KubeVela component is.

`register` writes the gateway Secret in the shape `vela cluster join` writes
(`connect.go:239`), so cluster-gateway treats the spoke as a virtual cluster with no extra
configuration.

---

## Security note before you start

The AWS environment file exports live STS session credentials. Never paste them into a
document, a ticket, a chat message, or a commit. They are temporary and expire, but treat any
that leak as compromised and let them expire rather than reusing the session.

Everything below sources credentials from the environment. No key material appears in any file
this runbook creates.

---

## Prerequisites

- Two atmos EKS clusters in the same account and region, one hub and one spoke.
- Neither needs KubeVela. The hub gets cluster-gateway only.
- Local checkout of the kubevela repo on a branch with the SpokeCluster work.
- `aws`, `kubectl`, `helm`, `make`, and Go toolchain.
- An IDE run configuration for `cmd/cluster-core`.

### Shell hygiene

```bash
export AWS_PAGER=""
```

Without this, AWS CLI v2 pipes output through `less` and every command looks like it opened an
editor. Press `q` to escape if you forget. Put it in your shell rc.

Two more, only if you work inside a devcontainer:

```bash
unset AWS_PROFILE     # the container ships AWS_PROFILE="" which breaks the credential helper
unset KUBECONFIG      # the env file may point at a macOS path that does not exist in the container
```

---

## Part 1: the clusters

Create the two atmos clusters without KubeVela and without the ng component. The clusters
themselves are ordinary atmos EKS clusters. Nothing in this runbook depends on how they were
provisioned, only on what is installed afterward.

Source credentials and confirm you are pointed at the hub:

```bash
source ~/.atmos2/<your-hub-session-env>
export AWS_PAGER=""
export REGION=us-west-2
export HUB=atmos-scratch-cghub
export SPOKE=atmos-scratch-cgspoke1
export ACCT=$(aws sts get-caller-identity --query Account --output text)
echo "ACCT=$ACCT"
```

`ACCT` must print a number. Blank means credentials are not loaded, and nothing below will work.

Confirm both clusters exist and the hub kubeconfig is active:

```bash
aws eks list-clusters --region $REGION
kubectl config current-context
kubectl get ns vela-system 2>/dev/null || echo "vela-system not present yet"
```

Note the cluster name as AWS knows it. `atmos-scratch-cghub`, not `cghub`. Using the short name
gives `ResourceNotFoundException: No cluster found for name`.

---

## Part 2: install cluster-gateway on the hub, and nothing else

`setup-cluster-gateway.sh` at the repo root does this. Run it with the hub kubeconfig active:

```bash
./setup-cluster-gateway.sh
```

It takes about nine minutes. What it does, in order:

1. `make core-install`, which regenerates CRDs and applies all of `charts/vela-core/crds/`
   including `spokeclusters.core.oam.dev`, and creates the `vela-system` namespace.
2. `make def-install`, which applies the component, trait, policy and workflow-step definitions.
3. Backs up `charts/vela-core/templates` to a temp directory.
4. Deletes every template except `cluster-gateway/`, `_helpers.tpl`,
   `kubevela-controller.yaml`, `addon_registry.yaml` and `NOTES.txt`, then truncates
   `kubevela-controller.yaml` at the Deployment boundary so only its RBAC survives.
5. `helm upgrade --install kubevela charts/vela-core -n vela-system` with
   `devLogs=true` and `multicluster.clusterGateway.secureTLS.enabled=false`.
6. Waits for the rollout, then restores the original templates from the backup.

Step 4 is the whole trick. It strips the chart down so the Helm release contains the gateway
Deployment, its Service, its APIService and the RBAC the gateway needs, without the vela-core
controller Deployment. Step 6 runs from an `EXIT` trap, so your working tree is restored even if
the install fails.

Verify:

```bash
kubectl get all -n vela-system
```

Expect exactly one pod, `kubevela-cluster-gateway-*`, `1/1 Running`, plus its Service,
Deployment and ReplicaSet. No `vela-core`, no `vela-cluster-core`.

```bash
kubectl get crd spokeclusters.core.oam.dev
kubectl get apiservice v1alpha1.cluster.core.oam.dev
```

---

## Part 3: the IAM role

You need **one** IAM role. It is what the controller assumes in order to describe the spoke and
mint a token for it.

```bash
export ROLE=oam-sc-cgspoke1-scoped
mkdir -p /tmp/scaws
```

Trust policy. The controller runs under your local AWS identity, so the role must trust you. On
a scratch account, trusting the account root is the simplest thing that works regardless of
whether you authenticate through SSO, a named role, or static keys:

```bash
cat > /tmp/scaws/trust.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Principal":{"AWS":"arn:aws:iam::${ACCT}:root"},
  "Action":"sts:AssumeRole"}]}
EOF
```

Permissions. One action on one cluster:

```bash
cat > /tmp/scaws/perms.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Action":"eks:DescribeCluster",
  "Resource":"arn:aws:eks:${REGION}:${ACCT}:cluster/${SPOKE}"}]}
EOF
```

Create:

```bash
aws iam create-role --role-name $ROLE \
  --assume-role-policy-document file:///tmp/scaws/trust.json \
  --tags Key=purpose,Value=spokecluster-test Key=owner,Value=$USER

aws iam put-role-policy --role-name $ROLE \
  --policy-name describe-spoke \
  --policy-document file:///tmp/scaws/perms.json
```

`EntityAlreadyExists` means the role is left over from a previous run. Inspect it rather than
recreating:

```bash
aws iam get-role --role-name $ROLE --query 'Role.AssumeRolePolicyDocument'
aws iam list-role-policies --role-name $ROLE
```

### Verify before going further

```bash
aws sts assume-role --role-arn arn:aws:iam::${ACCT}:role/${ROLE} \
  --role-session-name test --query 'AssumedRoleUser.Arn' --output text
```

---

## Part 4: let the role into the spoke

The role can now describe the spoke through the AWS API. It still has no Kubernetes permissions
on it.

### 4a: check the spoke's authentication mode

```bash
aws eks describe-cluster --name $SPOKE --region $REGION \
  --query 'cluster.accessConfig.authenticationMode' --output text
```

Access entries require `API` or `API_AND_CONFIG_MAP`. An atmos cluster is likely to be
`CONFIG_MAP`, in which case:

```
An error occurred (InvalidRequestException) when calling the ListAccessEntries operation:
The cluster's authentication mode must be set to one of [API, API_AND_CONFIG_MAP]
```

### 4b: switch the mode

**This is a one-way change.** `CONFIG_MAP` to `API_AND_CONFIG_MAP` cannot be reversed. It is
additive, so the existing `aws-auth` ConfigMap keeps working and nobody loses access, but the
cluster cannot go back. Confirm the cluster is disposable before running this.

```bash
aws eks update-cluster-config --name $SPOKE --region $REGION \
  --access-config authenticationMode=API_AND_CONFIG_MAP
```

Poll until it lands, roughly a minute:

```bash
aws eks describe-cluster --name $SPOKE --region $REGION \
  --query 'cluster.accessConfig.authenticationMode' --output text
```

### 4c: create the access entry

```bash
aws eks create-access-entry --cluster-name $SPOKE --region $REGION \
  --principal-arn arn:aws:iam::${ACCT}:role/${ROLE}

aws eks associate-access-policy --cluster-name $SPOKE --region $REGION \
  --principal-arn arn:aws:iam::${ACCT}:role/${ROLE} \
  --access-scope type=cluster \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminViewPolicy
```

Confirm:

```bash
aws eks list-access-entries --cluster-name $SPOKE --region $REGION
```

Your role ARN should appear alongside the cluster's own worker and bootstrap roles.

---

## Part 5: run cluster-core in your IDE

Run configuration:

- Package: `github.com/oam-dev/kubevela/cmd/cluster-core`
- Program arguments: `--use-webhook=false`
- Working directory: repo root
- Environment: `KUBECONFIG` pointing at the **hub** kubeconfig, plus the AWS credential
  variables from your session

The webhook is off because it blocks on TLS certificates that nothing provisions in this setup.
CRD-level validation still applies.

The process needs both halves of the environment at once: `KUBECONFIG` for the hub, and AWS
credentials for the STS and EKS calls. If your IDE cannot inherit the shell environment, export
the AWS variables into the run configuration explicitly.

Start it. The log should show the manager starting and the SpokeCluster controller registering.

> Reconstructed, not transcribed. The run this document is based on had cluster-core running in
> an IDE (the SpokeCluster reconciled, so something was watching it), but the exact run
> configuration was never captured. `--use-webhook=false` comes from the project's earlier
> local-testing notes. If the controller starts and reconciles without it, drop the flag.

---

## Part 6: apply the SpokeCluster and verify

```bash
mkdir -p localtest/clustergateway

cat > localtest/clustergateway/03-spokecluster-aws.yaml <<EOF
apiVersion: core.oam.dev/v1beta1
kind: SpokeCluster
metadata:
  name: cgspoke1
  namespace: vela-system
spec:
  mode: connect
  credential:
    type: aws
    aws:
      authMode: podIdentity
      clusterName: ${SPOKE}
      region: ${REGION}
      roleArn: arn:aws:iam::${ACCT}:role/${ROLE}
EOF

kubectl apply -f localtest/clustergateway/03-spokecluster-aws.yaml
```

No `externalId`. It is optional in the CRD and in the code (`aws.go:121-123`), and the trust
policy above carries no condition to match.

`authMode: podIdentity` is required by the schema but has no behavioral effect here. Nothing in
`defaultAWSClientFactory` branches on it; both `podIdentity` and `irsa` resolve through the same
`LoadDefaultConfig` call. The field records intent.

Watch it:

```bash
kubectl get spokecluster -n vela-system cgspoke1 -o wide -w
```

Expected, within about a minute:

```
NAME       MODE      VERSION               NODES  PLATFORM  STATUS     REGION     ENDPOINT             CPU  MEMORY    LATENCY  AUTH
cgspoke1   connect   v1.35.6-eks-8f14419   3      eks       Connected  us-west-2  https://...eks...    24   186.8Gi   321      aws
```

All four conditions:

```bash
kubectl get spokecluster -n vela-system cgspoke1 \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}{"\n"}{end}'
```

```
CredentialValid=True Materialized
Registered=True SecretMaterialized
Connected=True ProbeSucceeded
InfoSynced=True DiscoveryOK
```

> The first three lines were observed. `InfoSynced=True DiscoveryOK` was not: the verified run
> only printed conditions while discovery was still failing, and after the fix it checked the
> wide output instead. The reason string comes from `spokecluster_controller.go`, not from a
> terminal.

Two further checks, neither run during the verified session. They should work, and both are
worth doing, but treat a failure here as suspect tooling rather than a broken setup until you
have confirmed it another way.

The gateway Secret the controller wrote:

```bash
kubectl get secret -n vela-system cgspoke1 -o jsonpath='{.metadata.labels}'
kubectl get secret -n vela-system cgspoke1 -o jsonpath='{.data.endpoint}' | base64 -d; echo
```

Read-through to the spoke through the gateway:

```bash
kubectl get --raw \
  /apis/cluster.core.oam.dev/v1alpha1/clustergateways/cgspoke1/proxy/api/v1/namespaces \
  | head -c 300
```

---

## Troubleshooting

The conditions are written in a fixed order and the reconcile stops at the first hard failure
(`spokecluster_controller.go:111`). Wherever the `True` values stop is the layer that broke.

```bash
kubectl get spokecluster -n vela-system cgspoke1 \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{"\n"}{end}'
```

### CredentialValid=False

The AWS half failed before anything touched Kubernetes.

`MaterializeFailed` with an AssumeRole error means the trust policy does not admit your local
identity. Re-run the `aws sts assume-role` check from Part 3.

`MaterializeFailed` with `eks:DescribeCluster failed` means the role assumed fine but its
permission policy does not cover that cluster ARN. Check the region and cluster name in
`/tmp/scaws/perms.json`.

`NoProvider` means `spec.credential.type` does not match a registered provider.

### Registered=False

Rare. Usually a name collision. `register` refuses to overwrite a gateway Secret it does not own
(`connect.go:84`), so a Secret left behind by `vela cluster join` under the same name blocks it.
Delete the stale Secret or rename the SpokeCluster.

### Connected=False, ProbeFailed

The credential worked and the Secret was written, but the request could not reach the spoke.

Remember the path: hub apiserver, then the APIService, then the cluster-gateway pod, then the
spoke. The controller never dials the spoke directly.

- `unable to load root certificates: unable to parse bytes as PEM block` is the APIService
  caBundle placeholder. See Part 2.
- `401 Unauthorized` on EKS means the minted token was rejected. Historically caused by a
  missing `X-Amz-Expires` on the presigned URL, fixed at `aws_token.go:46-94`. Decode the token
  to check (Appendix A).
- `403` means AWS accepted the identity and the spoke's RBAC refused it. Missing or insufficient
  access entry.
- A dial timeout means the gateway pod cannot reach the spoke endpoint. Check whether the spoke
  has a private-only API endpoint.

Isolate the gateway from everything else with a request that involves no SpokeCluster and no
AWS:

```bash
kubectl get --raw /apis/cluster.core.oam.dev/v1alpha1/clustergateways/local/proxy/healthz
```

A TLS error there means the gateway itself is broken, not your credential.

### InfoSynced=False, nodes is forbidden

```
failed to list cluster nodes: nodes is forbidden: User "arn:aws:sts::...:assumed-role/
oam-sc-cgspoke1-scoped/aws-go-sdk-..." cannot list resource "nodes" in API group ""
at the cluster scope
```

`AmazonEKSViewPolicy` is not enough. It maps to the built-in `view` ClusterRole, which does not
grant read on cluster-scoped resources such as nodes. Add the admin-view policy:

```bash
aws eks associate-access-policy --cluster-name $SPOKE --region $REGION \
  --principal-arn arn:aws:iam::${ACCT}:role/${ROLE} \
  --access-scope type=cluster \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminViewPolicy
```

Multiple policies can attach to one access entry, so there is no need to remove the view one.
The next reconcile picks it up within the probe interval, 30 seconds by default.

Note that the spoke reports `Connected` throughout this. Discovery failure never fails the pass,
by design: a cluster that answers `/healthz` but refuses a node listing is still reachable.

### Nothing happens at all

No conditions, no status. The controller is not watching. Check the IDE process is running,
that its `KUBECONFIG` points at the hub, and that the CRD exists:

```bash
kubectl get crd spokeclusters.core.oam.dev
```

### AWS CLI opens what looks like an editor

That is `less`. Press `q`, then `export AWS_PAGER=""`.

### `aws: error: argument --region: expected one argument`

`$REGION` is empty. Re-export the variables from Part 1.

---

## What we did that turned out to be unnecessary

Recorded so the next person does not repeat it.

**Checking the Pod Identity agent addon.** The first thing we did on the hub was confirm the
agent was installed:

```bash
aws eks describe-addon --cluster-name $HUB --region $REGION \
  --addon-name eks-pod-identity-agent --query 'addon.status' --output text
# ACTIVE
```

The atmos hub already had it. It made no difference either way, for the reason below.

**The hub base role and the Pod Identity association.** We created `oam-sc-hub-base`, gave it an
`sts:AssumeRole` policy over the scoped role, and associated it with the `vela-core` service
account on the hub:

```bash
aws eks create-pod-identity-association --region $REGION --cluster-name $HUB \
  --namespace vela-system --service-account vela-core \
  --role-arn arn:aws:iam::${ACCT}:role/oam-sc-hub-base
```

None of it is used. Pod Identity injects credentials into a **pod**, and there is no controller
pod in this setup. The association sits there doing nothing.

Worse, it actively got in the way. The scoped role was first created with a trust policy naming
`oam-sc-hub-base` as principal and requiring the externalId
`us-west-2/<account>/atmos-scratch-cghub/vela-system/vela-core`. The local process is not that
role, so `sts:AssumeRole` failed until an account-root statement was added alongside the
original two:

```bash
aws iam update-assume-role-policy --role-name $ROLE --policy-document file:///tmp/scaws/trust.json
```

That widened policy, with the hub-base statements retained and a root statement appended, is
what the verified run used. Part 3 above gives the root statement alone, which is the same thing
minus the dead weight, but is not byte-identical to what was proven.

Keep any of this only if you later intend to run cluster-core as a pod on the hub. Otherwise
skip the two-role structure entirely, as Part 3 does.

**Inspecting the hub's `aws-auth` ConfigMap.** We looked at
`kubectl get cm aws-auth -n kube-system -o yaml` on the hub early on. It shows the atmos
cluster's existing role mappings and is useful orientation, but nothing in this flow reads or
writes it. The hub never needs an access entry either, since nothing assumes a role into it.

**The externalId.** The string
`us-west-2/<account>/<hub>/vela-system/vela-core` follows a Pod Identity convention, but nothing
in the controller computes it. `spec.credential.aws.externalId` is passed verbatim to STS. With
no Pod Identity, it is just a shared string that both the CR and the trust policy must agree on,
and omitting it is simpler.

---

## Cleanup

> Unverified. Nothing in this section was run during the verified session, so the resources it
> creates are all still live. The ordering below follows the AWS and finalizer dependencies and
> matches the equivalent section of the earlier EKS runbook, but it has not been executed
> against this setup.

Order matters. Delete the SpokeCluster while the controller is still running, so its finalizer
can detach the spoke and remove the gateway Secret. Delete the Helm release first and you get a
stuck object needing a manual finalizer patch.

```bash
# 1. Kubernetes, controller still running in the IDE
kubectl delete spokecluster -n vela-system cgspoke1
kubectl get secret -n vela-system cgspoke1   # should be gone

# 2. stop the IDE process, then the gateway
helm uninstall kubevela -n vela-system
kubectl delete crd spokeclusters.core.oam.dev

# 3. spoke access entry
aws eks delete-access-entry --cluster-name $SPOKE --region $REGION \
  --principal-arn arn:aws:iam::${ACCT}:role/${ROLE}

# 4. IAM, inline policy before the role
aws iam delete-role-policy --role-name $ROLE --policy-name describe-spoke
aws iam delete-role --role-name $ROLE

# 5. only if you created them, per the section above
ASSOC=$(aws eks list-pod-identity-associations --cluster-name $HUB --region $REGION \
  --query "associations[?serviceAccount=='vela-core'].associationId" --output text)
for a in $ASSOC; do
  aws eks delete-pod-identity-association --cluster-name $HUB --region $REGION --association-id $a
done
aws iam delete-role-policy --role-name oam-sc-hub-base --policy-name assume-scoped
aws iam delete-role --role-name oam-sc-hub-base
```

Verify nothing is left:

```bash
aws iam list-roles --query "Roles[?starts_with(RoleName,'oam-sc')].RoleName" --output text
aws eks list-access-entries --cluster-name $SPOKE --region $REGION | grep -c oam-sc
```

The spoke's authentication mode stays at `API_AND_CONFIG_MAP`. That cannot be undone.

---

## Appendix A: inspecting an EKS token

> Unverified in this setup. Carried over from the earlier EKS runbook, where it was used to
> diagnose a real 401. The token format it decodes is the one `aws_token.go:101` produces, so it
> should hold, but nothing here was run against `cgspoke1`.

A minted token is `k8s-aws-v1.` followed by a base64url-encoded presigned STS URL. When the
probe returns 401, this tells you whether the problem is identity or form.

```bash
TOK=<token from the gateway secret's data.token, base64-decoded>
PAYLOAD=$(echo "$TOK" | sed 's/^k8s-aws-v1.//')
python3 -c "
import base64, urllib.parse
p='$PAYLOAD'; p += '='*(-len(p)%4)
url = base64.urlsafe_b64decode(p).decode()
print('host+path:', url.split('?')[0])
q = urllib.parse.parse_qs(url.split('?',1)[1])
for k in ['X-Amz-Date','X-Amz-Expires','X-Amz-SignedHeaders','X-Amz-Credential']:
    print(k, '=', q.get(k, ['(MISSING)'])[0])
"
```

`X-Amz-Expires` missing means the token will be rejected regardless of identity.

Replay the URL the way EKS does, to see which identity resolves:

```bash
curl -s -H "x-k8s-aws-id: ${SPOKE}" "$PRESIGNED_URL" | grep -oE '<Arn>[^<]+</Arn>'
```

Correct ARN plus a 401 means the token's form is wrong. Wrong ARN means the IAM chain is wrong.

---

## Appendix B: the code path, for reference

| Step | Where | What it does |
|---|---|---|
| Provider lookup | `spokecluster_controller.go:119` | picks the aws provider from the registry |
| Materialize | `aws.go:71` | assume role, `DescribeCluster`, decode CA, mint token |
| Client factory | `aws.go:114` | `LoadDefaultConfig` then `NewAssumeRoleProvider` |
| Token mint | `aws_token.go:86` | presign STS `GetCallerIdentity`, bind with `x-k8s-aws-id` |
| Expiry fix | `aws_token.go:51-72` | Build-step middleware adding `X-Amz-Expires=60` |
| Register | `connect.go:239` | upsert the gateway Secret, token arm, credential-type label |
| Probe | `probe.go:57` | `/healthz` through cluster-gateway, measures latency |
| Discover | `discovery.go:52` | version, endpoint, latency |
| Node listing | `discovery.go:71` into `pkg/multicluster/o11n.go:61` | nodes, CPU, memory, and the platform/region heuristics |

Token refresh: `refreshAt = now + 15min - 1min` (`aws_token.go:102`). `nextRequeue` takes the
smaller of that and the probe interval, so a 30 second interval wins and the token is reminted
well before expiry. The local process must stay running for this.

---

# Quick reference: the whole thing, in order

Commands only. Every step has a checkpoint. If a checkpoint does not match, stop and go to the
corresponding part above rather than continuing.

| # | Step | Where |
|---|------|-------|
| 1 | Environment and variables | laptop |
| 2 | Install cluster-gateway | hub |
| 3 | Create the IAM role | AWS |
| 4 | Prove the role assumes | AWS |
| 5 | Switch spoke auth mode | AWS, one way |
| 6 | Grant the role into the spoke | AWS |
| 7 | Start cluster-core | IDE |
| 8 | Apply the SpokeCluster | hub |
| 9 | Verify | hub |

---

### 1. Environment and variables

```bash
source ~/.atmos2/<your-hub-session-env>
export AWS_PAGER=""
export REGION=us-west-2
export HUB=atmos-scratch-cghub
export SPOKE=atmos-scratch-cgspoke1
export ROLE=oam-sc-cgspoke1-scoped
export ACCT=$(aws sts get-caller-identity --query Account --output text)
mkdir -p /tmp/scaws
echo "ACCT=$ACCT"
kubectl config current-context
```

**Checkpoint.** `ACCT` prints a number, and the context is the hub. Cluster names are the full
AWS names, not the short atmos aliases.

---

### 2. Install cluster-gateway on the hub

```bash
./setup-cluster-gateway.sh
```

**Checkpoint.** About nine minutes, then:

```bash
kubectl get all -n vela-system
kubectl get crd spokeclusters.core.oam.dev
```

One pod, `kubevela-cluster-gateway-*`, `1/1 Running`. No vela-core, no vela-cluster-core. The
atmos label warnings and the `cuex` compiler errors during the run are both harmless.

---

### 3. Create the IAM role

```bash
cat > /tmp/scaws/trust.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Principal":{"AWS":"arn:aws:iam::${ACCT}:root"},
  "Action":"sts:AssumeRole"}]}
EOF

cat > /tmp/scaws/perms.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Action":"eks:DescribeCluster",
  "Resource":"arn:aws:eks:${REGION}:${ACCT}:cluster/${SPOKE}"}]}
EOF

aws iam create-role --role-name $ROLE \
  --assume-role-policy-document file:///tmp/scaws/trust.json \
  --tags Key=purpose,Value=spokecluster-test Key=owner,Value=$USER

aws iam put-role-policy --role-name $ROLE \
  --policy-name describe-spoke \
  --policy-document file:///tmp/scaws/perms.json
```

**If `EntityAlreadyExists`,** the role survives from an earlier run. Do not recreate it, widen it:

```bash
aws iam get-role --role-name $ROLE --query 'Role.AssumeRolePolicyDocument'
aws iam update-assume-role-policy --role-name $ROLE \
  --policy-document file:///tmp/scaws/trust.json
```

---

### 4. Prove the role assumes

```bash
aws sts assume-role --role-arn arn:aws:iam::${ACCT}:role/${ROLE} \
  --role-session-name test --query 'AssumedRoleUser.Arn' --output text
```

**Checkpoint.** Prints an ARN ending in `/test`. A failure here becomes an opaque controller
error later, so fix it now. Session names shorter than two characters fail validation.

---

### 5. Switch the spoke's authentication mode

```bash
aws eks describe-cluster --name $SPOKE --region $REGION \
  --query 'cluster.accessConfig.authenticationMode' --output text
```

Skip to step 6 if this already prints `API` or `API_AND_CONFIG_MAP`.

**This change cannot be undone.** It is additive, so existing `aws-auth` access survives, but the
cluster can never return to `CONFIG_MAP`. Confirm the cluster is disposable first.

```bash
aws eks update-cluster-config --name $SPOKE --region $REGION \
  --access-config authenticationMode=API_AND_CONFIG_MAP
```

**Checkpoint.** Poll for about a minute until it flips:

```bash
aws eks describe-cluster --name $SPOKE --region $REGION \
  --query 'cluster.accessConfig.authenticationMode' --output text
```

---

### 6. Grant the role into the spoke

```bash
aws eks create-access-entry --cluster-name $SPOKE --region $REGION \
  --principal-arn arn:aws:iam::${ACCT}:role/${ROLE}

for POLICY in AmazonEKSViewPolicy AmazonEKSAdminViewPolicy; do
  aws eks associate-access-policy --cluster-name $SPOKE --region $REGION \
    --principal-arn arn:aws:iam::${ACCT}:role/${ROLE} \
    --access-scope type=cluster \
    --policy-arn arn:aws:eks::aws:cluster-access-policy/${POLICY}
done
```

Both policies, because that is the combination proven to work. AdminView alone is very likely
enough and has not been tested.

**Checkpoint.**

```bash
aws eks list-access-entries --cluster-name $SPOKE --region $REGION
```

Your role ARN appears alongside the cluster's worker and bootstrap roles.

---

### 7. Start cluster-core in the IDE

| Setting | Value |
|---------|-------|
| Package | `github.com/oam-dev/kubevela/cmd/cluster-core` |
| Program arguments | `--use-webhook=false` |
| Working directory | repo root |
| Environment | `KUBECONFIG` for the **hub**, plus your AWS session variables |

**Checkpoint.** The log shows the manager starting and the SpokeCluster controller registering.
Leave it running: it remints the EKS token roughly every fourteen minutes.

---

### 8. Apply the SpokeCluster

```bash
mkdir -p localtest/clustergateway

cat > localtest/clustergateway/03-spokecluster-aws.yaml <<EOF
apiVersion: core.oam.dev/v1beta1
kind: SpokeCluster
metadata:
  name: cgspoke1
  namespace: vela-system
spec:
  mode: connect
  credential:
    type: aws
    aws:
      authMode: podIdentity
      clusterName: ${SPOKE}
      region: ${REGION}
      roleArn: arn:aws:iam::${ACCT}:role/${ROLE}
EOF

kubectl apply -f localtest/clustergateway/03-spokecluster-aws.yaml
```

No `externalId`, and `authMode` has no behavioral effect. Both are explained in Part 6.

---

### 9. Verify

```bash
kubectl get spokecluster -n vela-system cgspoke1 -o wide -w
```

**Checkpoint.** Within about a minute:

```
NAME       MODE      VERSION               NODES  PLATFORM  STATUS     REGION     CPU  MEMORY    LATENCY  AUTH
cgspoke1   connect   v1.35.6-eks-8f14419   3      eks       Connected  us-west-2  24   186.8Gi   321      aws
```

`Connected` with blank columns means the probe passed and discovery failed, which is not a
connectivity problem. Read the conditions:

```bash
kubectl get spokecluster -n vela-system cgspoke1 \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{"\n"}{end}'
```

Then find the failing condition in the troubleshooting section above.

---

### Afterwards

These resources stay live until you remove them. See the cleanup section, which is untested.

```
IAM role                oam-sc-cgspoke1-scoped
Spoke access entry      on atmos-scratch-cgspoke1
Helm release            kubevela, in vela-system on the hub
CRDs                    core.oam.dev, applied cluster wide
Spoke auth mode         API_AND_CONFIG_MAP, permanent
```
