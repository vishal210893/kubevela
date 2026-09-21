# OCI addon-as-component test

A real addon, published to an OCI registry on Docker Hub, consumed by an
Application through a `type: addon` component. It exists to exercise the path
that a git registry alone cannot: resolving an addon by manifest digest rather
than by crawling a directory tree.

## What is here

    addon/oci-widget/          the addon source
      metadata.yaml            name, version, tags
      template.cue             the addon's own Application; namespace first, then the rest
      parameter.cue            namespace and message, both with defaults
      resources/greeting.cue   a ConfigMap rendered from the parameters
      definitions/             a ComponentDefinition, so enabling it adds a capability
    app-oci-addon.yaml         an Application whose single component is type: addon

## Publish and register

The registry password is read from stdin, so it never reaches the process
arguments or the shell history.

    printf '%s' "$DOCKERHUB_TOKEN" | vela addon push \
      localtest/addon-component/nestmoduletest/addon/oci-widget \
      oci://registry-1.docker.io/<user> --username <user> --password-stdin

    printf '%s' "$DOCKERHUB_TOKEN" | vela addon registry add my-oci-addons \
      --type oci --endpoint=oci://registry-1.docker.io/<user> \
      --username=<user> --password-stdin

    vela addon list        # oci-widget should appear against my-oci-addons

The first push warns that the portable catalog was not updated: the catalog
repository does not exist yet, and Docker Hub answers `/v2/_catalog` with a
refusal rather than an empty list. Pushing a second time bootstraps it.

## Run it

    kubectl apply -f localtest/addon-component/nestmoduletest/app-oci-addon.yaml

## What a pass looks like

    $ kubectl get app -A
    NAMESPACE     NAME              COMPONENT       TYPE    PHASE     HEALTHY   STATUS
    default       oci-addon-app     oci-widget      addon   running   true      Ready:4/4
    vela-system   addon-oci-widget  ns-oci-widget   raw     running   true

The outer Application reports the owned Application's component count, and the
owned Application carries all four components of the addon:

    $ kubectl -n vela-system get app addon-oci-widget \
        -o jsonpath='{range .status.services[*]}{.name}={.healthy}{" "}{end}'
    ns-oci-widget=true addon-definitions=true addon-secret=true greeting=true

Both halves of the addon actually landed. The capability:

    $ kubectl -n vela-system get componentdefinition oci-widget-greeter
    oci-widget-greeter

And the resource, showing that the caller's parameter arrived and that the
rendered ConfigMap saw the addon's own metadata:

    $ kubectl -n oci-widget-system get cm oci-widget-greeting -o jsonpath='{.data}'
    {"addonVersion":"1.0.0","message":"pushed from localtest"}

## Why a second push is needed the first time

`vela addon push` writes the artifact, then tries to update a portable catalog
in the same registry so that listing works on registries without a usable
`/v2/_catalog`. On a first push there is no catalog to read, and Docker Hub's
auth service refuses a catalog-scoped token outright (400, not the 401 the
registry itself would return). Both conditions together used to read as a hard
failure, which made a Docker Hub OCI addon registry impossible to add at all.
`classifyCatalogAuthFailure` in `pkg/addon/backend_oci.go` now treats a refused
catalog-scoped token on Docker Hub the same as a refused catalog route: there
is nothing to enumerate, so a push may bootstrap one.
