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

package application

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	"k8s.io/apimachinery/pkg/util/validation/field"
	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	controller "github.com/oam-dev/kubevela/pkg/controller/core.oam.dev"
	"github.com/oam-dev/kubevela/pkg/oam/util"
)

var _ admission.Handler = &ValidatingHandler{}

// ValidatingHandler handles application
type ValidatingHandler struct {
	Client client.Client
	// Decoder decodes objects
	Decoder *admission.Decoder
}

func simplifyError(err error) error {
	switch e := err.(type) { // nolint
	case *field.Error:
		return fmt.Errorf("field \"%s\": %s error encountered, %s. ", e.Field, e.Type, e.Detail)
	default:
		return err
	}
}

func mergeErrors(errs field.ErrorList) error {
	s := ""
	for _, err := range errs {
		s += fmt.Sprintf("field \"%s\": %s error encountered, %s. ", err.Field, err.Type, err.Detail)
	}
	return errors.New(s)
}

// Handle validate Application Spec here
func (h *ValidatingHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting validation for Application",
		"resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)
	app := &v1beta1.Application{}
	if err := h.Decoder.Decode(req, app); err != nil {
		klog.ErrorS(err, "Failed to decode Application from request", "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}
	klog.V(1).InfoS("Successfully decoded Application for validation", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)

	if req.Namespace != "" {
		klog.V(1).InfoS("Setting Application namespace from request namespace", "appName", app.Name, "appNamespace", app.Namespace, "requestNamespace", req.Namespace, "uid", req.UID)
		app.Namespace = req.Namespace
	}

	ctx = util.SetNamespaceInCtx(ctx, app.Namespace)
	klog.V(1).InfoS("Set namespace in context for Application validation", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)

	switch req.Operation {
	case admissionv1.Create:
		klog.InfoS("Processing CREATE operation for Application", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
		if allErrs := h.ValidateCreate(ctx, app); len(allErrs) > 0 {
			mergedErr := mergeErrors(allErrs)
			klog.InfoS("Application CREATE validation failed", "appName", app.Name, "appNamespace", app.Namespace, "error", mergedErr.Error(), "uid", req.UID)
			// http.StatusUnprocessableEntity will NOT report any error descriptions
			// to the client, use generic http.StatusBadRequest instead.
			return admission.Errored(http.StatusBadRequest, mergedErr)
		}
		klog.InfoS("Application CREATE validation successful", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
	case admissionv1.Update:
		klog.InfoS("Processing UPDATE operation for Application", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
		oldApp := &v1beta1.Application{}
		if err := h.Decoder.DecodeRaw(req.AdmissionRequest.OldObject, oldApp); err != nil {
			simplifiedErr := simplifyError(err)
			klog.ErrorS(simplifiedErr, "Failed to decode old Application from request for UPDATE", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, simplifiedErr)
		}
		klog.V(1).InfoS("Successfully decoded old Application for UPDATE validation", "appName", oldApp.Name, "appNamespace", oldApp.Namespace, "uid", req.UID)
		if app.ObjectMeta.DeletionTimestamp.IsZero() {
			klog.V(1).InfoS("Application is not being deleted, proceeding with UPDATE validation", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
			if allErrs := h.ValidateUpdate(ctx, app, oldApp); len(allErrs) > 0 {
				mergedErr := mergeErrors(allErrs)
				klog.InfoS("Application UPDATE validation failed", "appName", app.Name, "appNamespace", app.Namespace, "error", mergedErr.Error(), "uid", req.UID)
				return admission.Errored(http.StatusBadRequest, mergedErr)
			}
			klog.InfoS("Application UPDATE validation successful", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
		} else {
			klog.InfoS("Application is being deleted, skipping UPDATE validation", "appName", app.Name, "appNamespace", app.Namespace, "uid", req.UID)
		}
	default:
		klog.InfoS("Operation is not CREATE or UPDATE for Application. No specific validation rules applied for this operation.",
			"appName", app.Name, "appNamespace", app.Namespace, "operation", req.Operation, "uid", req.UID)
		// Do nothing for DELETE and CONNECT
	}
	klog.InfoS("Application validation request allowed", "appName", app.Name, "appNamespace", app.Namespace, "operation", req.Operation, "uid", req.UID)
	return admission.ValidationResponse(true, "")
}

// RegisterValidatingHandler will register application validate handler to the webhook
func RegisterValidatingHandler(mgr manager.Manager, _ controller.Args) {
	klog.InfoS("Registering Application validating webhook handler", "path", "/validating-core-oam-dev-v1beta1-applications")
	server := mgr.GetWebhookServer()
	server.Register("/validating-core-oam-dev-v1beta1-applications", &webhook.Admission{Handler: &ValidatingHandler{
		Client:  mgr.GetClient(),
		Decoder: admission.NewDecoder(mgr.GetScheme()),
	}})
	klog.InfoS("Application validating webhook handler registered successfully", "path", "/validating-core-oam-dev-v1beta1-applications")
}
