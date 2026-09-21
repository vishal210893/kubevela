"regex-notmatch": {
	type: "component"
	annotations: {}
	labels: {}
	description: "Exercises defkit NotMatches negative regex conditions (issue #7353)"
	attributes: {
		workload: {
			definition: {
				apiVersion: "apps/v1"
				kind:       "Deployment"
			}
			type: "deployments.apps"
		}
	}
}
template: {
	output: {
		apiVersion: "apps/v1"
		kind:       "Deployment"
		metadata: {
			name: parameter.appName
		}
		spec: {
			selector: {
				matchLabels: {
					app: parameter.appName
				}
			}
			template: {
				metadata: {
					labels: {
						app: parameter.appName
						if parameter.env !~ "^prod-" {
							debug: "true"
						}
						if parameter.env =~ "^prod-" {
							tier: "production"
						}
					}
				}
				spec: {
					containers: [{
						name: parameter.appName
						image: parameter.image
					}]
				}
			}
		}
	}
	parameter: {
		// +usage=Deployment name; lowercase alphanumerics and dashes only
		appName: string
		// +usage=Environment name; anything starting with prod- is treated as production
		env: *"dev" | string
		// +usage=Container image
		image: *"nginx:alpine" | string
		_validate: {
			"appName contains unsupported characters": true
			if appName !~ "^[a-z0-9-]+$" {
				"appName contains unsupported characters": false
			}
		}
	}
}
