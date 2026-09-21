# OCI addon registry: local test setup

Manual verification for the change that folds the OCI addon registry into the
Helm registry, where an addon registry is a Helm source whose URL scheme picks
the transport.

Everything here runs against a real OCI registry (zot) over TLS. Plain HTTP is
not an option for the read path: containerd's resolver forces plain HTTP for any
loopback host, and the addon read path always uses the HTTPS clients, so the
registry has to be reachable on a non-loopback address with a certificate the
client trusts.

## Files

| File | Purpose |
|---|---|
| `01-gen-certs.sh` | Issues a CA and a server certificate for zot, with the container IP in the SANs |
| `02-run-zot.sh` | Runs zot over TLS on all interfaces and waits for it to answer |
| `03-push-addon.sh` | Packages `pkg/addon/testdata/example` and pushes it as an OCI Helm chart |
| `04-add-registry.sh` | Registers the OCI registry and reads it back through the CLI |
| `05-verify-record.sh` | Asserts the stored ConfigMap record is a Helm block with an `oci://` URL |
| `zot-in-cluster.yaml` | Runs zot inside the cluster instead, for a cluster that can pull images |
| `application-addon-component.yaml` | The declarative addon component under test |
| `application-addon-component-latest.yaml` | Same, resolving the latest version instead of a pin |

## Order

```bash
cd localtest/addon-component/oci-testing
./01-gen-certs.sh
./02-run-zot.sh
./03-push-addon.sh
./04-add-registry.sh
./05-verify-record.sh
kubectl apply -f application-addon-component.yaml
```

Every script writes to `$SCRATCH` (default `/tmp/vela-oci-test`) and expects
`SSL_CERT_FILE` to point at the bundle `01-gen-certs.sh` produces, which
`02-run-zot.sh` onward set for you.

## What was verified

Against k3d cluster `k3d-kubevela` with CRDs, definitions and webhooks
installed, using a `vela` binary built from this branch:

- `vela addon push <dir> oci://<host>/addons` created both `addons/example:1.0.1`
  and the portable catalog repo `addons/kubevela-addon-catalog`.
- `vela addon registry add --type oci` stored a `helm` block with an `oci://`
  URL and no `oci` block, and its validation genuinely listed the catalog.
- `vela addon registry list` and `get` reported the type as `oci`, derived from
  the URL.
- `vela addon ls` resolved the addon through catalog discovery and reported
  `AVAILABLE-VERSIONS [1.0.1]`.
- `vela addon status example` reported the registry and version.
- `vela addon enable example example=hello-oci --dry-run` rendered the child
  Application `addon-example` carrying `addons.oam.dev/registry: zot-oci` and
  `addons.oam.dev/version: 1.0.1`.

## Trusting the test CA from the IDE controller

The controller and webhook run on the host, outside this container, and reach
zot at the container IP over TLS. They need to trust the CA in
`tls/zot-test-ca.crt`.

`SSL_CERT_FILE` does not help on macOS: Go's `crypto/x509` uses Security
framework there and only reads that variable on Linux and the BSDs. So the CA
has to go into the keychain:

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  localtest/addon-component/oci-testing/tls/zot-test-ca.crt
```

Restart the controller afterwards. To remove it later:

```bash
sudo security delete-certificate -c zot-test-ca /Library/Keychains/System.keychain
```

A registry with a publicly trusted certificate avoids this entirely.

## What is still open

With the controller running from this branch, applying
`application-addon-component.yaml` reaches the webhook and is denied with:

```
"schematic": addon "example" version "1.0.1" not found in registries [zot-oci]:
registry "zot-oci": OCI registry zot-oci: failed to pull addon chart
172.17.0.8:5000/addons/example:1.0.1: ... read: connection reset by peer
```

That is the expected outcome for an untrusted certificate, and it confirms two
things. The wrapping text comes from the OCI backend's error classifier, so the
webhook does resolve the registry through the unified path. And the denial comes
from `pkg/addon/service/renderer.go:213`, the render service reached through
schematic validation, which is correct: a component whose chart cannot be
fetched cannot render. The addon compatibility checker is separate and fails
open on resolution errors, as designed.

Import the CA as described above and re-apply to complete the run.

## Docker Hub run (authenticated, publicly trusted certificate)

Docker Hub removes the certificate-trust problem and adds the coverage zot could
not give: authentication, the credential Secret round trip, and the full
declarative path through the webhook and controller.

Verified:

- `vela addon push <dir> oci://docker.io/<ns> --username <u> --password <pat>`
  pushed `<ns>/example:1.0.1`.
- `vela addon registry update ... --password-stdin` stored the record as
  `{"helm": {"url": "oci://docker.io/<ns>", "username": "<u>",
  "tokenSecretRef": "addon-registry-dockerhub"}}` and created Secret
  `addon-registry-dockerhub` with the credential under key `token`. The token
  appears nowhere in the ConfigMap.
- `vela addon status example` resolved through the registry, loading the
  credential back out of the Secret, and reported `[1.0.1]`.
- `kubectl apply -f application-addon-component-dockerhub.yaml` was admitted by
  the webhook and reconciled to `running`/healthy, with the child Application
  `addon-example` also `running`/healthy.
- The child carries `addons.oam.dev/name: example`,
  `addons.oam.dev/registry: dockerhub`, `addons.oam.dev/version: 1.0.1`.
- The addon's resources were applied: namespace `example-system`, service
  `source-controller`, ComponentDefinition `helm-example`, and ConfigMap
  `exampleinput` containing `{"input": "hello-from-dockerhub"}`, which is the
  component's `properties.example` value carried through the render.

## Bug found: the catalog fallback breaks Docker Hub

`vela addon registry add` for Docker Hub is rejected:

```
fail to add registry dockerhub: failed to list OCI addons from portable catalog
(portable OCI addon catalog repository docker.io/<ns>/kubevela-addon-catalog does not exist:
 ... 404 name unknown ... : OCI addon catalog does not exist)
and registry catalog (failed to decode OCI catalog response: invalid character '<' looking for beginning of value)
```

Two things go wrong, both in code this refactor moved without changing:

`listOCIRepositories` builds its request from the registry host verbatim, so it
asks `https://docker.io/v2/_catalog`. That host is Docker's website, not the
registry API, and it answers with an HTML page. Helm's client knows the
`docker.io` to `registry-1.docker.io` alias; this raw HTTP path does not.

The JSON decode failure is then classified as a read error rather than as
"this registry has no usable catalog API". Publishing requires *both* the
portable catalog and the registry catalog to report genuine absence before it
will bootstrap, so the HTML response permanently blocks the portable catalog
from ever being created on Docker Hub. `registry add`, which tolerates only
`ErrOCICatalogAbsent`, rejects the registry for the same reason.

The effect is that Docker Hub cannot be added as an addon registry at all, and
its portable catalog can never be bootstrapped. Everything that does not need
the catalog (push, direct resolve by name, install, the addon component) works,
which is why the run above succeeds using `registry update` to sidestep the
`add` validation.

A minimal fix is to treat a non-JSON catalog response as
`ErrOCICatalogAbsent`, since a registry answering HTML is not serving the
catalog API, and to resolve the `docker.io` alias before building the URL.

## Cluster note

The k3d cluster could not pull any image, including the `rancher/mirrored-pause`
sandbox image, failing with `x509: certificate signed by unknown authority`.
That is TLS interception on the host's egress and is unrelated to this change,
but it is why zot runs beside the cluster rather than in it. `zot-in-cluster.yaml`
is kept for an environment where image pulls work.
