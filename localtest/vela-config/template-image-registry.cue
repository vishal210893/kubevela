import (
	"encoding/json"
	"encoding/base64"
)

metadata: {
	name:        "demo-image-registry"
	alias:       "Demo Image Registry"
	description: "Store docker registry credentials as a dockerconfigjson secret."
	scope:       "namespace"
	sensitive:   false
}

template: {
	output: {
		apiVersion: "v1"
		kind:       "Secret"
		metadata: {
			name:      context.name
			namespace: context.namespace
		}
		type: "kubernetes.io/dockerconfigjson"
		stringData: {
			".dockerconfigjson": json.Marshal({
				auths: {
					"\(parameter.registry)": {
						username: parameter.username
						password: parameter.password
						auth:     base64.Encode(null, parameter.username + ":" + parameter.password)
					}
				}
			})
		}
	}

	parameter: {
		// +usage=The URL of the image registry, for example index.docker.io
		registry: *"index.docker.io" | string
		// +usage=The username used to log in to the registry
		username: string
		// +usage=The password or access token for the registry
		password: string
	}
}
