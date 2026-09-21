// Modules this addon brings with it. Each enabled entry becomes a
// type: module component in the addon's own Application, named after the
// module and depending on the addon's own resources, so the module's
// definitions never install before the addon's are healthy.
imports: [{
	module:  "oci-gadget"
	enabled: true
	sources: [{
		// Resolved from this named module registry at render time.
		registry: "my-oci-modules"
		// An exact pin. A range is rejected at addon build/publish time.
		version: "1.0.0"
	}]
}]
