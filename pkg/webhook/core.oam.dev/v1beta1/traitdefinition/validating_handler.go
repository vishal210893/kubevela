/*
Copyright 2021 The KubeVela Authors.

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

package traitdefinition

import (
	"context"
	"fmt"
	"net/http"

	"github.com/pkg/errors"
	admissionv1 "k8s.io/api/admission/v1"
	"k8s.io/klog/v2" // Using klog
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	"github.com/oam-dev/kubevela/pkg/appfile"
	controller "github.com/oam-dev/kubevela/pkg/controller/core.oam.dev"
	"github.com/oam-dev/kubevela/pkg/oam"
	webhookutils "github.com/oam-dev/kubevela/pkg/webhook/utils"
)

const (
	errValidateDefRef = "error occurs when validating definition reference"

	failInfoDefRefOmitted = "if definition reference is omitted, patch or output with GVK is required"
)

var traitDefGVR = v1beta1.SchemeGroupVersion.WithResource("traitdefinitions")

// ValidatingHandler handles validation of trait definition
type ValidatingHandler struct {
	Client client.Client

	// Decoder decodes object
	Decoder *admission.Decoder
	// Validators validate objects
	Validators []TraitDefValidator
}

// TraitDefValidator validate trait definition
type TraitDefValidator interface {
	Validate(context.Context, v1beta1.TraitDefinition) error
}

// TraitDefValidatorFn implements TraitDefValidator
type TraitDefValidatorFn func(context.Context, v1beta1.TraitDefinition) error

// Validate implements TraitDefValidator method
func (fn TraitDefValidatorFn) Validate(ctx context.Context, td v1beta1.TraitDefinition) error {
	return fn(ctx, td)
}

var _ admission.Handler = &ValidatingHandler{}

// Handle validate trait definition
func (h *ValidatingHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting validation for TraitDefinition",
		"resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)
	obj := &v1beta1.TraitDefinition{}
	if req.Resource.String() != traitDefGVR.String() {
		err := fmt.Errorf("expect resource to be %s", traitDefGVR)
		klog.ErrorS(err, "Resource mismatch for incoming request", "expectedGVR", traitDefGVR.String(), "actualGVR", req.Resource.String(), "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}

	if req.Operation == admissionv1.Create || req.Operation == admissionv1.Update {
		err := h.Decoder.Decode(req, obj)
		if err != nil {
			klog.ErrorS(err, "Failed to decode TraitDefinition", "name", req.Name, "namespace", req.Namespace, "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, err)
		}
		klog.InfoS("Successfully decoded TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "uid", req.UID)

		for i, validator := range h.Validators {
			if err := validator.Validate(ctx, *obj); err != nil {
				klog.InfoS("Custom validator failed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "validatorIndex", i, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
		}
		klog.V(1).InfoS("All custom validators passed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "uid", req.UID)

		// validate cueTemplate
		if obj.Spec.Schematic != nil && obj.Spec.Schematic.CUE != nil {
			klog.V(1).InfoS("Validating CUE template for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "uid", req.UID)
			err = webhookutils.ValidateCueTemplate(obj.Spec.Schematic.CUE.Template)
			if err != nil {
				klog.InfoS("CUE template validation failed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("CUE template validation successful for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "uid", req.UID)
		}

		if obj.Spec.Version != "" {
			klog.V(1).InfoS("Validating semantic version for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
			err = webhookutils.ValidateSemanticVersion(obj.Spec.Version)
			if err != nil {
				klog.InfoS("Semantic version validation failed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "version", obj.Spec.Version, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Semantic version validation successful for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "version", obj.Spec.Version, "uid", req.UID)
		}

		revisionName := obj.GetAnnotations()[oam.AnnotationDefinitionRevisionName]
		if len(revisionName) != 0 {
			defRevName := fmt.Sprintf("%s-v%s", obj.Name, revisionName)
			klog.V(1).InfoS("Validating definition revision for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "revisionName", revisionName, "defRevNameForLookup", defRevName, "uid", req.UID)
			err = webhookutils.ValidateDefinitionRevision(ctx, h.Client, obj, client.ObjectKey{Namespace: obj.Namespace, Name: defRevName})
			if err != nil {
				klog.InfoS("Definition revision validation failed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
				return admission.Denied(err.Error())
			}
			klog.V(1).InfoS("Definition revision validation successful for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "revisionName", revisionName, "uid", req.UID)
		}

		version := obj.Spec.Version
		klog.V(1).InfoS("Validating for multiple definition versions presence for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "uid", req.UID)
		err = webhookutils.ValidateMultipleDefVersionsNotPresent(version, revisionName, obj.Kind)
		if err != nil {
			klog.InfoS("Multiple definition versions validation failed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "version", version, "revisionName", revisionName, "error", err.Error(), "uid", req.UID)
			return admission.Denied(err.Error())
		}
		klog.InfoS("All validations for CREATE/UPDATE passed for TraitDefinition", "traitName", obj.Name, "traitNamespace", obj.Namespace, "operation", req.Operation, "uid", req.UID)
	}
	klog.InfoS("TraitDefinition validation request allowed", "name", req.Name, "namespace", req.Namespace, "operation", req.Operation, "uid", req.UID)
	return admission.ValidationResponse(true, "")
}

// RegisterValidatingHandler will register TraitDefinition validation to webhook
func RegisterValidatingHandler(mgr manager.Manager, _ controller.Args) {
	klog.InfoS("Registering TraitDefinition validating webhook handler", "path", "/validating-core-oam-dev-v1beta1-traitdefinitions")
	server := mgr.GetWebhookServer()
	server.Register("/validating-core-oam-dev-v1beta1-traitdefinitions", &webhook.Admission{Handler: &ValidatingHandler{
		Client:  mgr.GetClient(),
		Decoder: admission.NewDecoder(mgr.GetScheme()),
		Validators: []TraitDefValidator{
			TraitDefValidatorFn(ValidateDefinitionReference),
			// add more validators here
		},
	}})
	klog.InfoS("TraitDefinition validating webhook handler registered successfully", "path", "/validating-core-oam-dev-v1beta1-traitdefinitions")
}

// ValidateDefinitionReference validates whether the trait definition is valid if
// its `.spec.reference` field is unset.
// It's valid if
// it has at least one output, and all outputs must have GVK
// or it has no output but has a patch
// or it has a patch and outputs, and all outputs must have GVK
// TODO(roywang) currently we only validate whether it contains CUE template.
// Further validation, e.g., output with GVK, valid patch, etc, remains to be done.
func ValidateDefinitionReference(_ context.Context, td v1beta1.TraitDefinition) error {
	klog.V(1).InfoS("Starting ValidateDefinitionReference for TraitDefinition", "traitName", td.Name, "traitNamespace", td.Namespace)
	if len(td.Spec.Reference.Name) > 0 {
		klog.V(1).InfoS("Definition reference is present, skipping further validation in ValidateDefinitionReference", "traitName", td.Name, "traitNamespace", td.Namespace, "referenceName", td.Spec.Reference.Name)
		return nil
	}
	klog.V(1).InfoS("Definition reference is not present, proceeding with CUE template validation", "traitName", td.Name, "traitNamespace", td.Namespace)
	capability, err := appfile.ConvertTemplateJSON2Object(td.Name, td.Spec.Extension, td.Spec.Schematic)
	if err != nil {
		klog.ErrorS(err, "Failed to convert template JSON to object during definition reference validation", "traitName", td.Name, "traitNamespace", td.Namespace)
		return errors.WithMessage(err, errValidateDefRef)
	}
	if capability.CueTemplate == "" {
		klog.InfoS("Validation failed: CUE template is empty when definition reference is omitted", "traitName", td.Name, "traitNamespace", td.Namespace)
		return errors.New(failInfoDefRefOmitted)
	}
	klog.V(1).InfoS("ValidateDefinitionReference successful for TraitDefinition", "traitName", td.Name, "traitNamespace", td.Namespace)
	return nil
}
