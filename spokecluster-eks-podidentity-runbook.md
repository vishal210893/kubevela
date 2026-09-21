# Connecting an EKS spoke to an EKS hub with Pod Identity

Connects a SpokeCluster on a hub EKS cluster to a spoke EKS cluster, with vela-cluster-core
running as a pod and authenticating through EKS Pod Identity.

Credential chain:

```
Pod Identity agent  ->  hub base role  ->  per-spoke scoped role  ->  spoke EKS API
```

The pod holds one base identity. For each spoke it assumes a narrow role that can describe
exactly one cluster. IAM gets the controller a valid token; an EKS access entry decides what
that token may do inside the spoke.

## Prerequisites

Two EKS clusters in the same account and region, one hub and one spoke. Neither needs
KubeVela preinstalled.

On the hub, these three pods running in `vela-system`:

```
kubevela-cluster-gateway
kubevela-vela-core
kubevela-vela-core-cluster-core
```

### Building the image

EKS nodes are amd64. Building on an Apple Silicon Mac produces arm64 binaries that fail with
`exec format error`, and building the repo Dockerfile under `--platform linux/amd64` runs the
Go toolchain in QEMU, where `go mod download` crashes. Cross-compile on the host instead and
package the binaries in a thin image.

```bash
cd ~/Open_Source/kubevela

VELA_VERSION="$(git rev-parse --abbrev-ref HEAD)"
GIT_COMMIT="$(git rev-parse HEAD)"

rm -rf /tmp/scimg-amd64 && mkdir -p /tmp/scimg-amd64

CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /tmp/scimg-amd64/manager \
  -ldflags "-s -w -X github.com/oam-dev/kubevela/version.VelaVersion=${VELA_VERSION} -X github.com/oam-dev/kubevela/version.GitRevision=${GIT_COMMIT}" \
  ./cmd/core/main.go

CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /tmp/scimg-amd64/cluster-manager \
  -ldflags "-s -w -X github.com/oam-dev/kubevela/version.VelaVersion=${VELA_VERSION} -X github.com/oam-dev/kubevela/version.GitRevision=${GIT_COMMIT}" \
  ./cmd/cluster-core/main.go

cp entrypoint.sh /tmp/scimg-amd64/

cat > /tmp/scimg-amd64/Dockerfile <<'DOCKERFILE'
FROM --platform=linux/amd64 alpine:3.18
RUN apk add --no-cache ca-certificates bash expat
WORKDIR /
COPY manager /usr/local/bin/manager
COPY cluster-manager /usr/local/bin/cluster-manager
COPY entrypoint.sh /usr/local/bin/
ENTRYPOINT ["entrypoint.sh"]
CMD ["manager"]
DOCKERFILE

aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin 776719623202.dkr.ecr.us-west-2.amazonaws.com

docker buildx build --platform linux/amd64 \
  -t 776719623202.dkr.ecr.us-west-2.amazonaws.com/atmos-component/ccs-atmos-kubevela:latest \
  -f /tmp/scimg-amd64/Dockerfile /tmp/scimg-amd64 --push
```

### Installing the chart

Use Helm 3. Helm 4 hangs on the chart's pre-install hook.

```bash
export IMAGE_NAME=776719623202.dkr.ecr.us-west-2.amazonaws.com/atmos-component/ccs-atmos-kubevela
export IMAGE_TAG=latest

helm upgrade --install kubevela charts/vela-core \
  --create-namespace --namespace vela-system \
  --set imageRegistry="" \
  --set image.repository="$IMAGE_NAME" \
  --set image.tag="$IMAGE_TAG" \
  --set image.pullPolicy=Always \
  --set featureGates.enableCueExpVariable=false \
  --set featureGates.enableClusterInfrastructure=true \
  --set multicluster.clusterGateway.secureTLS.enabled=false \
  --wait --timeout 6m
```

`featureGates.enableClusterInfrastructure=true` is required. Without it the cluster-core
Deployment, its ServiceAccount, and its RBAC do not render.

Leave `clusterCore.aws.serviceAccountRoleArn` unset. Setting it adds an
`eks.amazonaws.com/role-arn` annotation to the service account, which injects IRSA
environment variables that take priority over Pod Identity in the credential chain.

---

## Step 0: variables

```bash
export ACCT=776719623202
export REGION=us-west-2
export HUB=atmos-scratch-cgspoke2
export SPOKE=atmos-scratch-cgspoke3
export HUB_ROLE=oam-sc-hub2-base
export ROLE=oam-sc-cgspoke3-scoped
export AWS_PAGER=""
mkdir -p /tmp/scaws
```

## Step 1: identify the service account

The Pod Identity association must name the pod's service account exactly.

```bash
kubectl -n vela-system get pod -l controller.oam.dev/name=vela-cluster-core \
  -o jsonpath='{.items[0].spec.serviceAccountName}{"\n"}'
```

```bash
export SA=kubevela-vela-core-cluster-core
```

Confirm it carries no IRSA annotation:

```bash
kubectl -n vela-system get sa $SA -o jsonpath='{.metadata.annotations}{"\n"}'
```

**Checkpoint.** Only Helm annotations should appear. An `eks.amazonaws.com/role-arn` key means
IRSA would win over Pod Identity; reinstall with `clusterCore.aws.serviceAccountRoleArn` unset.

## Step 2: Pod Identity agent on the hub

```bash
aws eks create-addon --cluster-name $HUB --region $REGION \
  --addon-name eks-pod-identity-agent

aws eks describe-addon --cluster-name $HUB --region $REGION \
  --addon-name eks-pod-identity-agent --query 'addon.status' --output text
```

**Checkpoint.** `ACTIVE`. `ResourceInUseException` on create means the addon is already
installed; continue.

## Step 3: hub base role

Trusted by the EKS Auth service, and permitted to assume the scoped role. Both `sts:AssumeRole`
and `sts:TagSession` are required on each side, because Pod Identity sessions carry session tags.

```bash
cat > /tmp/scaws/hub-trust.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Principal":{"Service":"pods.eks.amazonaws.com"},
  "Action":["sts:AssumeRole","sts:TagSession"]}]}
EOF

cat > /tmp/scaws/hub-perms.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Action":["sts:AssumeRole","sts:TagSession"],
  "Resource":"arn:aws:iam::${ACCT}:role/${ROLE}"}]}
EOF

aws iam create-role --role-name $HUB_ROLE \
  --assume-role-policy-document file:///tmp/scaws/hub-trust.json

aws iam put-role-policy --role-name $HUB_ROLE \
  --policy-name assume-spoke-roles \
  --policy-document file:///tmp/scaws/hub-perms.json
```

`EntityAlreadyExists` on create-role means the role survives from an earlier run. Skip the
create and run the two policy commands, adding `update-assume-role-policy` for the trust document.

## Step 4: per-spoke scoped role

The external ID binds the assume to one hub, namespace, and service account, so a role ARN
leaked elsewhere is not enough on its own. Build the string first, because the same value goes
into the SpokeCluster at step 9 and the two must match exactly.

```bash
export EXTID=${REGION}/${ACCT}/${HUB}/vela-system/${SA}
```

The trust policy needs two statements. `sts:ExternalId` is not available in the request context
when `sts:TagSession` is authorized, so a single statement carrying both actions plus the
condition denies TagSession and the assume fails. Keep the condition on the assume only.

```bash
cat > /tmp/scaws/scoped-trust.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Principal":{"AWS":"arn:aws:iam::${ACCT}:role/${HUB_ROLE}"},
  "Action":"sts:AssumeRole",
  "Condition":{"StringEquals":{"sts:ExternalId":"${EXTID}"}}},
 {"Effect":"Allow",
  "Principal":{"AWS":"arn:aws:iam::${ACCT}:role/${HUB_ROLE}"},
  "Action":"sts:TagSession"}]}
EOF

cat > /tmp/scaws/scoped-perms.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow",
  "Action":"eks:DescribeCluster",
  "Resource":"arn:aws:eks:${REGION}:${ACCT}:cluster/${SPOKE}"}]}
EOF

aws iam create-role --role-name $ROLE \
  --assume-role-policy-document file:///tmp/scaws/scoped-trust.json

aws iam put-role-policy --role-name $ROLE \
  --policy-name describe-spoke \
  --policy-document file:///tmp/scaws/scoped-perms.json
```

`EntityAlreadyExists` on create-role means the role survives from an earlier run. Skip the
create and run `update-assume-role-policy` with the trust document before `put-role-policy`.
This is mandatory if `$HUB` changed since the last run. The external ID embeds the hub name,
so the surviving trust policy still demands the old string while the SpokeCluster presents the
new one, and the assume is denied with a message that names the role rather than the condition
that failed.

`eks:DescribeCluster` is the only AWS API call the controller makes. Minting the bearer token
is local presigning and needs no permission.

## Step 5: Pod Identity association

```bash
aws eks create-pod-identity-association --cluster-name $HUB --region $REGION \
  --namespace vela-system --service-account $SA \
  --role-arn arn:aws:iam::${ACCT}:role/${HUB_ROLE}
```

## Step 6: restart the controller

The association only affects newly created pods.

```bash
kubectl -n vela-system rollout restart deploy/kubevela-vela-core-cluster-core
kubectl -n vela-system rollout status deploy/kubevela-vela-core-cluster-core

POD=$(kubectl -n vela-system get pod -l controller.oam.dev/name=vela-cluster-core -o name | head -1)
kubectl -n vela-system exec $POD -- env | grep AWS_CONTAINER
```

**Checkpoint.** Both variables must appear:

```
AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE=/var/run/secrets/pods.eks.amazonaws.com/serviceaccount/eks-pod-identity-token
AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/v1/credentials
```

Nothing there means the association's namespace or service account does not match the pod.
Fix that before continuing.

## Step 7: spoke authentication mode

Access entries require `API` or `API_AND_CONFIG_MAP`.

```bash
aws eks describe-cluster --name $SPOKE --region $REGION \
  --query 'cluster.accessConfig.authenticationMode' --output text
```

If it returns `CONFIG_MAP`:

> **This change is irreversible.** AWS will not move a cluster back to `CONFIG_MAP`.
> `API_AND_CONFIG_MAP` keeps the existing `aws-auth` ConfigMap working, so nothing that
> depends on it breaks.

```bash
aws eks update-cluster-config --name $SPOKE --region $REGION \
  --access-config authenticationMode=API_AND_CONFIG_MAP
```

**Checkpoint.** Re-run the describe until it reports `API_AND_CONFIG_MAP`. Takes a minute or two.

## Step 8: access entry on the spoke

The access entry registers the IAM role with the cluster. The policy associations grant it
Kubernetes RBAC.

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

`AmazonEKSViewPolicy` alone is not enough. It maps to the built-in `view` ClusterRole, which
excludes cluster-scoped resources, so discovery fails when it lists nodes.
`AmazonEKSAdminViewPolicy` covers those.

Note that `AmazonEKSAdminViewPolicy` grants read access to Kubernetes Secrets across the whole
cluster. Acceptable on a scratch cluster. For anything else, use a purpose-built ClusterRole
granting `list` on nodes instead.

## Step 9: apply the SpokeCluster

```bash
cat <<EOF | kubectl apply -f -
apiVersion: core.oam.dev/v1beta1
kind: SpokeCluster
metadata:
  name: cgspoke3
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
      externalId: ${EXTID}
  probeIntervalSeconds: 30
  probeTimeoutSeconds: 10
  deletionPolicy: detach
EOF
```

## Step 10: verify

```bash
kubectl get spokecluster -n vela-system -o wide

kubectl -n vela-system get spokecluster cgspoke3 \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{"\n"}{end}'
```

All four conditions true:

```
CredentialValid=True Materialized: credential materialized for endpoint https://...eks.amazonaws.com
Registered=True SecretMaterialized: gateway secret is up to date
Connected=True ProbeSucceeded: spoke answered the healthz probe
InfoSynced=True DiscoveryOK: cluster inventory refreshed
```

Table:

```
NAME       MODE      VERSION               STATUS      REGION      ENDPOINT                  AUTH
cgspoke3   connect   v1.35.6-eks-8f14419   Connected   us-west-2   https://...               aws
```

---

## Troubleshooting

Conditions are ordered. Reconcile stops at the first hard failure, so fix them top down.

**`CredentialValid=False` with `AccessDenied ... sts:TagSession`**

Either the hub role's identity policy omits `sts:TagSession` (step 3), or the scoped role's
trust policy puts `sts:TagSession` in the same statement as the `sts:ExternalId` condition
(step 4). The condition key is absent when TagSession is authorized, so it must sit in its own
unconditioned statement. Check both:

```bash
aws iam get-role-policy --role-name $HUB_ROLE --policy-name assume-spoke-roles --output json
aws iam get-role --role-name $ROLE --query 'Role.AssumeRolePolicyDocument'
```

The status message caches the last failure. Compare the `RequestID` between reads to tell a
stale message from a fresh retry, and restart the deployment to force one.

**`CredentialValid=False` with `AccessDenied ... eks:DescribeCluster`**

Scoped role permissions policy is missing or names the wrong cluster ARN. Step 4.

**`Connected=False`**

The token is valid but the spoke rejects it. The access entry is missing. Step 8.

**`InfoSynced=False` with `nodes is forbidden`**

Only `AmazonEKSViewPolicy` is attached. Add `AmazonEKSAdminViewPolicy`. Step 8.

**Pod in `CrashLoopBackOff` with `exec format error`**

The image is arm64. Rebuild for amd64 per the prerequisites.

---

## Cleanup

```bash
kubectl -n vela-system delete spokecluster cgspoke3

aws eks delete-access-entry --cluster-name $SPOKE --region $REGION \
  --principal-arn arn:aws:iam::${ACCT}:role/${ROLE}

ASSOC=$(aws eks list-pod-identity-associations --cluster-name $HUB --region $REGION \
  --query "associations[?serviceAccount=='${SA}'].associationId" --output text)
aws eks delete-pod-identity-association --cluster-name $HUB --region $REGION \
  --association-id $ASSOC

aws iam delete-role-policy --role-name $ROLE --policy-name describe-spoke
aws iam delete-role --role-name $ROLE

aws iam delete-role-policy --role-name $HUB_ROLE --policy-name assume-spoke-roles
aws iam delete-role --role-name $HUB_ROLE

helm uninstall kubevela -n vela-system
```

The spoke's `authenticationMode` stays on `API_AND_CONFIG_MAP` permanently.
