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

package policydefinition

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

var policyDefGVR = v1beta1.SchemeGroupVersion.WithResource("policydefinitions")

// ValidatingHandler handles validation of policy definition
type ValidatingHandler struct {
	// Decoder decodes object
	Decoder *admission.Decoder
	Client  client.Client
}

var _ admission.Handler = &ValidatingHandler{}

// Handle validate component definition
func (h *ValidatingHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting validation for PolicyDefinition",
		"resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)

	obj := &v1beta1.PolicyDefinition{}
	if req.Resource.String() != policyDefGVR.String() {
		err := fmt.Errorf("expect resource to be %s", policyDefGVR)
		klog.ErrorS(err, "Resource mismatch for incoming request", "expectedGVR", policyDefGVR.String(), "actualGVR", req.Resource.String(), "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}

	if req.Operation == admissionv1.Create || req.Operation == admissionv1.Update {
		err := h.Decoder.Decode(req, obj)
		if err != nil {
			klog.ErrorS(err, "Failed to decode PolicyDefinition", "name", req.Name, "namespace", req.Namespace, "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, err)
		}
		klog.InfoS("Successfully decoded PolicyDefinition", "policyName", obj.Name, "policyNamespace", obj.Namespace, "uid", req.UID)

		// validate cueTemplate
		if obj.Spec.Schematic != nil && obj.Spec.Schematic.CUE != nil {
			klog.V(1).InfoS("Validating CUE template", "policyName", obj.Name, "policyNamespace", obj.Namespace, "uid", req.UID)
			err = webhookutils.ValidateCueTemplate(obj.Spec.Schematic.CUE.Template)
			if err != nil {
				klog.InfoS("CUE template validation failed", "policyName", obj.Name, "policyNamespace", obj.Namespace, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("CUE template validation successful", "policyName", obj.Name, "policyNamespace", obj.Namespace, "uid", req.UID)
		}

		if obj.Spec.Version != "" {
			klog.V(1).InfoS("Validating semantic version", "policyName", obj.Name, "policyNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
			err = webhookutils.ValidateSemanticVersion(obj.Spec.Version)
			if err != nil {
				klog.InfoS("Semantic version validation failed", "policyName", obj.Name, "policyNamespace", obj.Namespace, "version", obj.Spec.Version, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Semantic version validation successful", "policyName", obj.Name, "policyNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
		}

		revisionName := obj.GetAnnotations()[oam.AnnotationDefinitionRevisionName]
		if len(revisionName) != 0 {
			defRevName := fmt.Sprintf("%s-v%s", obj.Name, revisionName)
			klog.V(1).InfoS("Validating definition revision", "policyName", obj.Name, "policyNamespace", obj.Namespace, "revisionName", revisionName, "defRevNameForLookup", defRevName, "uid", req.UID)
			err = webhookutils.ValidateDefinitionRevision(ctx, h.Client, obj, client.ObjectKey{Namespace: obj.Namespace, Name: defRevName})
			if err != nil {
				klog.InfoS("Definition revision validation failed", "policyName", obj.Name, "policyNamespace", obj.Namespace, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Definition revision validation successful", "policyName", obj.Name, "policyNamespace", obj.Namespace, "revisionName", revisionName, "uid", req.UID)
		}

		version := obj.Spec.Version
		klog.V(1).InfoS("Validating for multiple definition versions presence", "policyName", obj.Name, "policyNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "uid", req.UID)
		err = webhookutils.ValidateMultipleDefVersionsNotPresent(version, revisionName, obj.Kind)
		if err != nil {
			klog.InfoS("Multiple definition versions validation failed", "policyName", obj.Name, "policyNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
			return admission.Denied(err.Error())
		}
		klog.V(1).InfoS("Multiple definition versions validation successful", "policyName", obj.Name, "policyNamespace", obj.Namespace, "uid", req.UID)

		klog.InfoS("All validations for CREATE/UPDATE passed for PolicyDefinition", "policyName", obj.Name, "policyNamespace", obj.Namespace, "uid", req.UID)
	}
	klog.InfoS("PolicyDefinition validation request allowed", "name", req.Name, "namespace", req.Namespace, "operation", req.Operation, "uid", req.UID)
	return admission.ValidationResponse(true, "")
}

// RegisterValidatingHandler will register ComponentDefinition validation to webhook
func RegisterValidatingHandler(mgr manager.Manager) {
	klog.InfoS("Registering PolicyDefinition validating webhook handler", "path", "/validating-core-oam-dev-v1beta1-policydefinitions")

	server := mgr.GetWebhookServer()
	server.Register("/validating-core-oam-dev-v1beta1-policydefinitions", &webhook.Admission{Handler: &ValidatingHandler{
		Client:  mgr.GetClient(),
		Decoder: admission.NewDecoder(mgr.GetScheme()),
	}})
	klog.InfoS("PolicyDefinition validating webhook handler registered successfully", "path", "/validating-core-oam-dev-v1beta1-policydefinitions")
}
