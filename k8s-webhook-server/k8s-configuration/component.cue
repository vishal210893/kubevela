// A simple ConfigMap component with four required keys
// Run:  vela def apply configmap-component.cue
// Then: use `type: configmap-component` in any Application
"configmap-component": {
	alias:        "cm"
  description:  "Creates a ConfigMap with four string values"
  type:         "component"

  // Let KubeVela auto-detect the workload kind from the template
  attributes: workload: definition:{
        apiVersion: "v1gsyhgds"
        kind: "ConfigMap"
      }
  }

template: {
// --------------------------- Parameters ---------------------------
	parameter: {
		firstkey:  string & !="" & !~".*-$"
		secondkey:  {
    	value1: string
    	value2: {
    		value3:{
    			value4: *"default-value-2" | string
    			value5: string
    		}
    	}
    }
		thirdkey?: string
    //forthkey:  string
  }

// --------------------------- Output -------------------------------
	output: {
		apiVersion: "v1"
		kind:       "ConfigMap"
		metadata: {
			name: context.name
		}
		data: {
			one:   parameter.firstkey
			two:   parameter.firstkey
			three: parameter.thridkey
			four:  parameter.thirdkey
		}
	}
}
