# oci-widget

A small but complete addon used to exercise the `type: addon` component against an
OCI registry.

It ships both halves of a real addon:

- `definitions/oci-widget-greeter.yaml` installs a ComponentDefinition, so enabling
  the addon adds a capability to the cluster.
- `resources/greeting.cue` renders a ConfigMap from a parameter, so a caller can see
  its own input arrive.

`template.cue` creates the namespace first and applies everything else after, which is
the ordering every addon in the catalog uses.
