/*
 Copyright 2021. The KubeVela Authors.

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

package componentdefinition

import (
	"context"
	"fmt"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	git "k8s.io/klog/v2" // Using klog
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/common"
	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	"github.com/oam-dev/kubevela/pkg/oam"
	"github.com/oam-dev/kubevela/pkg/oam/util"
	webhookutils "github.com/oam-dev/kubevela/pkg/webhook/utils"
)

var componentDefGVR = v1beta1.SchemeGroupVersion.WithResource("componentdefinitions")

// ValidatingHandler handles validation of component definition
type ValidatingHandler struct {
	// Decoder decodes object
	Decoder *admission.Decoder
	Client  client.Client
}

var _ admission.Handler = &ValidatingHandler{}

// Handle validate ComponentDefinition Spec here
func (h *ValidatingHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting validation for ComponentDefinition",
		"resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)

	obj := &v1beta1.ComponentDefinition{}
	if req.Resource.String() != componentDefGVR.String() {
		err := fmt.Errorf("expected resource to be %s, got %s", componentDefGVR, req.Resource.String())
		klog.ErrorS(err, "Resource mismatch for incoming request", "expectedGVR", componentDefGVR.String(), "actualGVR", req.Resource.String(), "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}

	if req.Operation == admissionv1.Create || req.Operation == admissionv1.Update {
		klog.InfoS("Processing CREATE/UPDATE operation", "name", req.Name, "namespace", req.Namespace, "operation", req.Operation, "uid", req.UID)
		err := h.Decoder.Decode(req, obj)
		if err != nil {
			klog.ErrorS(err, "Failed to decode ComponentDefinition", "name", req.Name, "namespace", req.Namespace, "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, err)
		}
		klog.InfoS("Successfully decoded ComponentDefinition", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)

		klog.V(1).InfoS("Validating workload definition", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
		err = ValidateWorkload(h.Client.RESTMapper(), obj)
		if err != nil {
			klog.InfoS("Workload validation failed", "componentName", obj.Name, "componentNamespace", obj.Namespace, "error", err.Error(), "uid", req.UID)
			return admission.Denied(err.Error())
		}
		klog.V(1).InfoS("Workload validation successful", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)

		if obj.Spec.Schematic != nil && obj.Spec.Schematic.CUE != nil {
			klog.V(1).InfoS("Validating CUE template", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
			err = webhookutils.ValidateCueTemplate(obj.Spec.Schematic.CUE.Template)
			if err != nil {
				klog.InfoS("CUE template validation failed", "componentName", obj.Name, "componentNamespace", obj.Namespace, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("CUE template validation successful", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
		} else {
			klog.V(1).InfoS("No CUE template specified in schematic, skipping CUE validation", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
		}

		if obj.Spec.Version != "" {
			klog.V(1).InfoS("Validating semantic version", "componentName", obj.Name, "componentNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
			err = webhookutils.ValidateSemanticVersion(obj.Spec.Version)
			if err != nil {
				klog.InfoS("Semantic version validation failed", "componentName", obj.Name, "componentNamespace", obj.Namespace, "version", obj.Spec.Version, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Semantic version validation successful", "componentName", obj.Name, "componentNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
		} else {
			klog.V(1).InfoS("No version specified, skipping semantic version validation", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
		}

		revisionName := obj.GetAnnotations()[oam.AnnotationDefinitionRevisionName]
		if len(revisionName) != 0 {
			defRevName := fmt.Sprintf("%s-v%s", obj.Name, revisionName)
			klog.V(1).InfoS("Validating definition revision", "componentName", obj.Name, "componentNamespace", obj.Namespace, "revisionName", revisionName, "defRevNameForLookup", defRevName, "uid", req.UID)
			err = webhookutils.ValidateDefinitionRevision(ctx, h.Client, obj, client.ObjectKey{Namespace: obj.Namespace, Name: defRevName})
			if err != nil {
				klog.InfoS("Definition revision validation failed", "componentName", obj.Name, "componentNamespace", obj.Namespace, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Definition revision validation successful", "componentName", obj.Name, "componentNamespace", obj.Namespace, "revisionName", revisionName, "uid", req.UID)
		} else {
			klog.V(1).InfoS("No definition revision annotation found, skipping revision validation", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
		}

		version := obj.Spec.Version
		klog.V(1).InfoS("Validating for multiple definition versions presence", "componentName", obj.Name, "componentNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "uid", req.UID)
		err = webhookutils.ValidateMultipleDefVersionsNotPresent(version, revisionName, obj.Kind)
		if err != nil {
			klog.InfoS("Multiple definition versions validation failed", "componentName", obj.Name, "componentNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
			return admission.Denied(err.Error())
		}
		klog.V(1).InfoS("Multiple definition versions validation successful", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)

		klog.InfoS("All validations for CREATE/UPDATE passed for ComponentDefinition", "componentName", obj.Name, "componentNamespace", obj.Namespace, "uid", req.UID)
	}
	// Note: The 'else' block that was previously here to log other operations has been removed
	// to strictly adhere to "only add log" without changing control flow.

	klog.InfoS("ComponentDefinition validation request allowed", "name", req.Name, "namespace", req.Namespace, "operation", req.Operation, "uid", req.UID)
	return admission.ValidationResponse(true, "")
}

// RegisterValidatingHandler will register ComponentDefinition validation to webhook
func RegisterValidatingHandler(mgr manager.Manager) {
	klog.InfoS("Registering ComponentDefinition validating webhook handler", "path", "/validating-core-oam-dev-v1beta1-componentdefinitions")

	server := mgr.GetWebhookServer()
	server.Register("/validating-core-oam-dev-v1beta1-componentdefinitions", &webhook.Admission{Handler: &ValidatingHandler{
		Client:  mgr.GetClient(),
		Decoder: admission.NewDecoder(mgr.GetScheme()),
	}})
	klog.InfoS("ComponentDefinition validating webhook handler registered successfully", "path", "/validating-core-oam-dev-v1beta1-componentdefinitions")
}

// ValidateWorkload validates whether the Workload field is valid
func ValidateWorkload(mapper meta.RESTMapper, cd *v1beta1.ComponentDefinition) error {
	klog.V(1).InfoS("Starting workload validation", "componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace)

	if cd.Spec.Workload.Type == "" && cd.Spec.Workload.Definition == (common.WorkloadGVK{}) {
		err := fmt.Errorf("neither the type nor the definition of the workload field in the ComponentDefinition %s can be empty", cd.Name)
		klog.InfoS("Validation failed: workload type and definition are both empty", "componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace, "error", err.Error())
		return err
	}

	if cd.Spec.Workload.Type != "" && cd.Spec.Workload.Definition != (common.WorkloadGVK{}) {
		klog.V(1).InfoS("Validating consistency between workload type and definition", "componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace, "workloadType", cd.Spec.Workload.Type, "workloadDefinitionGVK", cd.Spec.Workload.Definition)
		defRef, err := util.ConvertWorkloadGVK2Definition(mapper, cd.Spec.Workload.Definition)
		if err != nil {
			klog.ErrorS(err, "Failed to convert workload GVK to definition reference", "componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace, "workloadDefinitionGVK", cd.Spec.Workload.Definition)
			return err
		}
		if defRef.Name != cd.Spec.Workload.Type {
			err := fmt.Errorf("the type ('%s') and the definition ('%s' from GVK %v) of the workload field in ComponentDefinition %s should represent the same workload",
				cd.Spec.Workload.Type, defRef.Name, cd.Spec.Workload.Definition, cd.Name)
			klog.InfoS("Validation failed: workload type and definition mismatch",
				"componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace,
				"specifiedType", cd.Spec.Workload.Type,
				"derivedTypeFromDefinition", defRef.Name,
				"error", err.Error())
			return fmt.Errorf("the type and the definition of the workload field in ComponentDefinition %s should represent the same workload", cd.Name)
		}
		klog.V(1).InfoS("Workload type and definition are consistent", "componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace)
	}
	klog.V(1).InfoS("Workload validation successful", "componentdefinition_name", cd.Name, "componentdefinition_namespace", cd.Namespace)
	return nil
}
