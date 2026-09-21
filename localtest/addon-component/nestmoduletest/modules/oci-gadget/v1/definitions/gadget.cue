// The capability this module offers. The key becomes the definition's
// metadata.name, installed as <module>-<apiVersion>-<capability>, so this
// lands in the cluster as oci-gadget-v1-gadget.
"gadget": {
	type: "component"
	attributes: workload: type: "autodetects.core.oam.dev"
}

template: {
	output: {
		apiVersion: "v1"
		kind:       "ConfigMap"
		metadata: name: context.name
		data: {
			gadget: parameter.label
			// Proves the rendered resource saw the module's own context.
			renderedBy: "oci-gadget-v1"
		}
	}

	parameter: {
		// What this gadget records.
		label: *"gadget" | string
	}
}
