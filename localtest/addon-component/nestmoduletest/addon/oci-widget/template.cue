output: {
	apiVersion: "core.oam.dev/v1beta1"
	kind:       "Application"
	metadata: {
		name:      "oci-widget"
		namespace: "vela-system"
	}
	spec: {
		components: [{
			name: "ns-oci-widget"
			type: "raw"
			properties: {
				apiVersion: "v1"
				kind:       "Namespace"
				metadata: name: parameter.namespace
			}
		}]
		workflow: steps: [{
			name: "apply-ns"
			type: "apply-component"
			properties: component: "ns-oci-widget"
		}, {
			name: "apply-resources"
			type: "apply-remaining"
		}]
	}
}
