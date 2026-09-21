// Package workflowsteps contains KubeVela WorkflowStepDefinition implementations.
// Workflow steps define actions that can be executed in application workflows.
//
// To create a new workflow step:
//
//	func init() {
//	    defkit.Register(MyStep())
//	}
//
//	func MyStep() *defkit.WorkflowStepDefinition {
//	    return defkit.NewWorkflowStep("my-step").
//	        Description("My workflow step description").
//	        // ... configuration
//	}
package workflowsteps
