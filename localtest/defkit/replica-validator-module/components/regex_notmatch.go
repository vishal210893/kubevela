/*
Copyright 2022 The KubeVela Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

	http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package components

import (
	"github.com/oam-dev/kubevela/pkg/definition/defkit"
)

func init() {
	defkit.Register(RegexNotMatch())
}

// RegexNotMatch exercises issue #7353 and PR #7352: the NotMatches fluent
// helpers on StringParam and LocalFieldRef, which render CUE's native negative
// regex operator !~ instead of wrapping a positive match in Not(...).
//
// The component covers three paths at once:are
//
//   - a validator that fails when a field does not match an allowed pattern,
//     via LocalFieldRef.NotMatches
//   - a conditional field guarded by StringParam.NotMatches
//   - the symmetric positive guard on the same parameter, via StringParam.Matches
//
// so the generated definition should contain both !~ and =~ for the same
// parameter, and the validator should reject names with unsupported characters.
func RegexNotMatch() *defkit.ComponentDefinition {
	appName := defkit.String("appName").
		Description("Deployment name; lowercase alphanumerics and dashes only")
	env := defkit.String("env").
		Default("dev").
		Description("Environment name; anything starting with prod- is treated as production")
	image := defkit.String("image").
		Default("nginx:alpine").
		Description("Container image")

	nameValidator := defkit.Validate("appName contains unsupported characters").
		FailWhen(defkit.LocalField("appName").NotMatches(`^[a-z0-9-]+$`))

	return defkit.NewComponent("regex-notmatch").
		Description("Exercises defkit NotMatches negative regex conditions (issue #7353)").
		Workload("apps/v1", "Deployment").
		Params(appName, env, image).
		Validators(nameValidator).
		Template(func(tpl *defkit.Template) {
			d := defkit.NewResource("apps/v1", "Deployment").
				Set("metadata.name", appName).
				Set("spec.selector.matchLabels.app", appName).
				Set("spec.template.metadata.labels.app", appName).
				SetIf(env.Matches(`^prod-`), "spec.template.metadata.labels.tier", defkit.Lit("production")).
				SetIf(env.NotMatches(`^prod-`), "spec.template.metadata.labels.debug", defkit.Lit("true")).
				Set("spec.template.spec.containers[0].name", appName).
				Set("spec.template.spec.containers[0].image", image)
			tpl.Output(d)
		})
}
