output: {
	type: "raw"
	properties: {
		apiVersion: "v1"
		kind:       "ConfigMap"
		metadata: {
			name:      "oci-widget-greeting"
			namespace: parameter.namespace
		}
		data: {
			message: parameter.message
			// Proves the rendered resource saw the addon's own metadata.
			addonVersion: context.metadata.version
		}
	}
}
