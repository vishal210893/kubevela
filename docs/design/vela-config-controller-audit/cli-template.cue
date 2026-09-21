// Reproducible fixture for the Vela Config controller audit.
metadata: {
  name:        "audit-cli-template"
  alias:       "CLI Template"
  description: "description should survive CLI conversion"
  scope:       "project"
  sensitive:   false
}

template: {
  output: {
    apiVersion: "v1"
    kind:       "Secret"
    metadata: name: context.name
    stringData: value: parameter.value
  }
  parameter: value: string
}
