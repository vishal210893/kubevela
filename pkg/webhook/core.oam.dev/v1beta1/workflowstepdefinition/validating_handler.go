/*
Copyright 2024 The KubeVela Authors.

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

package workflowstepdefinition

import (
	"context"
	"fmt"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	"k8s.io/klog/v2" // Using klog
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	"github.com/oam-dev/kubevela/pkg/oam"
	webhookutils "github.com/oam-dev/kubevela/pkg/webhook/utils"
)

var workflowStepDefGVR = v1beta1.SchemeGroupVersion.WithResource("workflowstepdefinitions")

// ValidatingHandler handles validation of workflow step definition
type ValidatingHandler struct {
	// Decoder decodes object
	Decoder *admission.Decoder
	Client  client.Client
}

// InjectClient injects the client into the ValidatingHandler
func (h *ValidatingHandler) InjectClient(c client.Client) error {
	klog.V(1).InfoS("Injecting client into WorkflowStepDefinition ValidatingHandler")
	h.Client = c
	return nil
}

// InjectDecoder injects the decoder into the ValidatingHandler
func (h *ValidatingHandler) InjectDecoder(d *admission.Decoder) error {
	klog.V(1).InfoS("Injecting decoder into WorkflowStepDefinition ValidatingHandler")
	h.Decoder = d
	return nil
}

// Handle validate WorkflowStepDefinition Spec here
func (h *ValidatingHandler) Handle(_ context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting validation for WorkflowStepDefinition",
		"resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)
	obj := &v1beta1.WorkflowStepDefinition{}
	if req.Resource.String() != workflowStepDefGVR.String() {
		err := fmt.Errorf("expect resource to be %s", workflowStepDefGVR)
		klog.ErrorS(err, "Resource mismatch for incoming request", "expectedGVR", workflowStepDefGVR.String(), "actualGVR", req.Resource.String(), "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}

	if req.Operation == admissionv1.Create || req.Operation == admissionv1.Update {
		klog.InfoS("Processing CREATE/UPDATE operation for WorkflowStepDefinition", "name", req.Name, "namespace", req.Namespace, "operation", req.Operation, "uid", req.UID)
		err := h.Decoder.Decode(req, obj)
		if err != nil {
			klog.ErrorS(err, "Failed to decode WorkflowStepDefinition", "name", req.Name, "namespace", req.Namespace, "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, err)
		}
		klog.InfoS("Successfully decoded WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "uid", req.UID)

		if obj.Spec.Version != "" {
			klog.V(1).InfoS("Validating semantic version for WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
			err = webhookutils.ValidateSemanticVersion(obj.Spec.Version)
			if err != nil {
				klog.InfoS("Semantic version validation failed for WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "version", obj.Spec.Version, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Semantic version validation successful for WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
		}
		revisionName := obj.Annotations[oam.AnnotationDefinitionRevisionName]
		version := obj.Spec.Version
		klog.V(1).InfoS("Validating for multiple definition versions presence for WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "uid", req.UID)
		err = webhookutils.ValidateMultipleDefVersionsNotPresent(version, revisionName, obj.Kind)
		if err != nil {
			klog.InfoS("Multiple definition versions validation failed for WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
			return admission.Denied(err.Error())
		}
		klog.InfoS("All validations for CREATE/UPDATE passed for WorkflowStepDefinition", "workflowStepDefName", obj.Name, "workflowStepDefNamespace", obj.Namespace, "operation", req.Operation, "uid", req.UID)
	}
	klog.InfoS("WorkflowStepDefinition validation request allowed", "name", req.Name, "namespace", req.Namespace, "operation", req.Operation, "uid", req.UID)
	return admission.ValidationResponse(true, "")
}

// RegisterValidatingHandler will register WorkflowStepDefinition validation to webhook
func RegisterValidatingHandler(mgr manager.Manager) {
	klog.InfoS("Registering WorkflowStepDefinition validating webhook handler", "path", "/validating-core-oam-dev-v1beta1-workflowstepdefinitions")
	server := mgr.GetWebhookServer()
	server.Register("/validating-core-oam-dev-v1beta1-workflowstepdefinitions", &webhook.Admission{Handler: &ValidatingHandler{}})
	klog.InfoS("WorkflowStepDefinition validating webhook handler registered successfully", "path", "/validating-core-oam-dev-v1beta1-workflowstepdefinitions")
}
