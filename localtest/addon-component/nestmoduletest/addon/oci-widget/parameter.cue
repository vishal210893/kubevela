parameter: {
	// Namespace the addon creates and writes its ConfigMap into.
	namespace: *"oci-widget-system" | string
	// Message the addon records, so a caller can see its parameter arrive.
	message: *"hello from oci" | string
}
