// Package traits contains KubeVela TraitDefinition implementations.
// Traits modify or enhance components with additional capabilities.
//
// To create a new trait:
//
//	func init() {
//	    defkit.Register(MyTrait())
//	}
//
//	func MyTrait() *defkit.TraitDefinition {
//	    return defkit.NewTrait("my-trait").
//	        Description("My trait description").
//	        AppliesToWorkloads("deployments.apps").
//	        // ... configuration
//	}
package traits
