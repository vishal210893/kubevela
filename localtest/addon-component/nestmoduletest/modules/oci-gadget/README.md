# oci-gadget

A module published to an OCI registry and pulled in by the `oci-widget` addon
through `modules/_imports.cue`, so the nesting an addon can create is exercised
end to end:

    Application (type: addon)
      -> addon-oci-widget          the addon's own Application
           -> type: module component, emitted from the addon's _imports
                -> module-oci-gadget   the module's own Application
                     -> oci-gadget-v1-gadget   the ComponentDefinition it installs

It offers one capability, `gadget`, which renders a ConfigMap from a parameter.

## Publish

    printf '%s' "$DOCKERHUB_TOKEN" | vela module registry add my-oci-modules \
      oci://registry-1.docker.io/<user> --username <user> --password-stdin

    vela module publish localtest/addon-component/nestmoduletest/modules/oci-gadget \
      --registry my-oci-modules

A published version is immutable. To change the module, bump `version` in
`_module.cue` and publish again.
