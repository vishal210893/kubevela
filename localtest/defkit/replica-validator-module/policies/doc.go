// Package policies contains KubeVela PolicyDefinition implementations.
// Policies define application-level behaviors and constraints.
//
// To create a new policy:
//
//	func init() {
//	    defkit.Register(MyPolicy())
//	}
//
//	func MyPolicy() *defkit.PolicyDefinition {
//	    return defkit.NewPolicy("my-policy").
//	        Description("My policy description").
//	        // ... configuration
//	}
package policies
