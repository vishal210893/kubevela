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

package application

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/kubevela/pkg/controller/sharding"
	"github.com/pkg/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	utilfeature "k8s.io/apiserver/pkg/util/feature"
	"k8s.io/klog/v2"
	"k8s.io/utils/strings/slices"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	"github.com/oam-dev/kubevela/pkg/auth"
	"github.com/oam-dev/kubevela/pkg/features"
	"github.com/oam-dev/kubevela/pkg/oam"
	"github.com/oam-dev/kubevela/pkg/utils"
)

// MutatingHandler adding user info to application annotations
type MutatingHandler struct {
	skipUsers []string
	Decoder   *admission.Decoder
}

var _ admission.Handler = &MutatingHandler{}

type appMutator func(ctx context.Context, req admission.Request, oldApp *v1beta1.Application, newApp *v1beta1.Application) (bool, error)

func (h *MutatingHandler) handleIdentity(_ context.Context, req admission.Request, _ *v1beta1.Application, app *v1beta1.Application) (bool, error) {
	klog.V(1).InfoS("Entering handleIdentity", "appName", app.Name, "appNamespace", app.Namespace, "userName", req.UserInfo.Username)
	if !utilfeature.DefaultMutableFeatureGate.Enabled(features.AuthenticateApplication) {
		klog.V(1).InfoS("AuthenticateApplication feature gate is disabled, skipping identity handling", "appName", app.Name, "appNamespace", app.Namespace)
		return false, nil
	}

	if slices.Contains(h.skipUsers, req.UserInfo.Username) {
		klog.V(1).InfoS("User is in skipUsers list, skipping identity handling", "appName", app.Name, "appNamespace", app.Namespace, "userName", req.UserInfo.Username)
		return false, nil
	}

	if metav1.HasAnnotation(app.ObjectMeta, oam.AnnotationApplicationServiceAccountName) {
		klog.InfoS("Application has service-account annotation, which is not permitted when authentication enabled", "appName", app.Name, "appNamespace", app.Namespace)
		return false, errors.New("service-account annotation is not permitted when authentication enabled")
	}
	klog.Infof("[ApplicationMutatingHandler] Setting UserInfo into Application, UserInfo: %v, Application: %s/%s", req.UserInfo, app.GetNamespace(), app.GetName())
	auth.SetUserInfoInAnnotation(&app.ObjectMeta, req.UserInfo)
	klog.V(1).InfoS("Successfully set UserInfo in annotation", "appName", app.Name, "appNamespace", app.Namespace)
	return true, nil
}

func (h *MutatingHandler) handleWorkflow(_ context.Context, _ admission.Request, _ *v1beta1.Application, app *v1beta1.Application) (modified bool, err error) {
	klog.V(1).InfoS("Entering handleWorkflow", "appName", app.Name, "appNamespace", app.Namespace)
	if app.Spec.Workflow != nil {
		klog.V(1).InfoS("Processing workflow steps", "appName", app.Name, "appNamespace", app.Namespace, "numSteps", len(app.Spec.Workflow.Steps))
		for i, step := range app.Spec.Workflow.Steps {
			if step.Name == "" {
				newName := fmt.Sprintf("step-%d", i)
				klog.V(1).InfoS("Mutating empty workflow step name", "appName", app.Name, "appNamespace", app.Namespace, "stepIndex", i, "newName", newName)
				app.Spec.Workflow.Steps[i].Name = newName
				modified = true
			}
			for j, sub := range step.SubSteps {
				if sub.Name == "" {
					newSubName := fmt.Sprintf("step-%d-%d", i, j)
					klog.V(1).InfoS("Mutating empty workflow sub-step name", "appName", app.Name, "appNamespace", app.Namespace, "stepIndex", i, "subStepIndex", j, "newSubName", newSubName)
					app.Spec.Workflow.Steps[i].SubSteps[j].Name = newSubName
					modified = true
				}
			}
		}
	}
	klog.V(1).InfoS("Finished handleWorkflow", "appName", app.Name, "appNamespace", app.Namespace, "modified", modified)
	return modified, nil
}

func (h *MutatingHandler) handleSharding(_ context.Context, _ admission.Request, oldApp *v1beta1.Application, newApp *v1beta1.Application) (bool, error) {
	klog.V(1).InfoS("Entering handleSharding", "appName", newApp.Name, "appNamespace", newApp.Namespace)
	if sharding.EnableSharding && !utilfeature.DefaultMutableFeatureGate.Enabled(features.DisableWebhookAutoSchedule) {
		klog.V(1).InfoS("Sharding enabled and DisableWebhookAutoSchedule feature gate is not enabled", "appName", newApp.Name, "appNamespace", newApp.Namespace)
		oid, scheduled := sharding.GetScheduledShardID(oldApp)
		_, newScheduled := sharding.GetScheduledShardID(newApp)
		if scheduled && !newScheduled {
			klog.Infof("inherit old shard-id %s for app %s/%s", oid, newApp.Namespace, newApp.Name)
			sharding.SetScheduledShardID(newApp, oid)
			klog.V(1).InfoS("Finished handleSharding, inherited old shard-id", "appName", newApp.Name, "appNamespace", newApp.Namespace, "shardID", oid, "modified", true)
			return true, nil
		}
		klog.V(1).InfoS("Attempting to schedule with DefaultScheduler", "appName", newApp.Name, "appNamespace", newApp.Namespace)
		modified := sharding.DefaultScheduler.Get().Schedule(newApp)
		klog.V(1).InfoS("Finished handleSharding with DefaultScheduler", "appName", newApp.Name, "appNamespace", newApp.Namespace, "modified", modified)
		return modified, nil
	}
	klog.V(1).InfoS("Sharding not applicable or disabled by feature gate, skipping sharding handling", "appName", newApp.Name, "appNamespace", newApp.Namespace, "EnableSharding", sharding.EnableSharding, "DisableWebhookAutoScheduleEnabled", utilfeature.DefaultMutableFeatureGate.Enabled(features.DisableWebhookAutoSchedule))
	return false, nil
}

// Handle mutate application
func (h *MutatingHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting mutation for Application", "resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)
	oldApp, newApp := &v1beta1.Application{}, &v1beta1.Application{}
	if err := h.Decoder.Decode(req, newApp); err != nil {
		klog.ErrorS(err, "Failed to decode new Application from request", "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}
	klog.V(1).InfoS("Successfully decoded new Application", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)

	if len(req.OldObject.Raw) > 0 {
		if err := h.Decoder.DecodeRaw(req.OldObject, oldApp); err != nil {
			klog.ErrorS(err, "Failed to decode old Application from request", "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, err)
		}
		klog.V(1).InfoS("Successfully decoded old Application", "appName", oldApp.Name, "appNamespace", oldApp.Namespace, "uid", req.UID)
	}

	modified := false
	for _, handler := range []appMutator{h.handleIdentity, h.handleSharding, h.handleWorkflow} {
		klog.V(1).InfoS("Executing app mutator", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)
		m, err := handler(ctx, req, oldApp, newApp)
		if err != nil {
			klog.ErrorS(err, "Application mutator failed", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)
			return admission.Errored(http.StatusBadRequest, err)
		}
		if m {
			klog.V(1).InfoS("Application mutator resulted in modification", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)
			modified = true
		}
	}
	if !modified {
		klog.InfoS("No modifications made by mutators, returning Patched admission response", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)
		return admission.Patched("")
	}

	klog.InfoS("Application was modified, marshalling and creating patch response", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)
	bs, err := json.Marshal(newApp)
	if err != nil {
		klog.ErrorS(err, "Failed to marshal mutated Application", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID)
		return admission.Errored(http.StatusInternalServerError, err)
	}
	resp := admission.PatchResponseFromRaw(req.AdmissionRequest.Object.Raw, bs)
	klog.InfoS("Successfully created patch response for Application", "appName", newApp.Name, "appNamespace", newApp.Namespace, "uid", req.UID, "numPatches", len(resp.Patches))
	return resp
}

// RegisterMutatingHandler will register component mutation handler to the webhook
func RegisterMutatingHandler(mgr manager.Manager) {
	klog.InfoS("Registering Application mutating webhook handler", "path", "/mutating-core-oam-dev-v1beta1-applications")
	server := mgr.GetWebhookServer()
	handler := &MutatingHandler{
		Decoder: admission.NewDecoder(mgr.GetScheme()),
	}
	if userInfo := utils.GetUserInfoFromConfig(mgr.GetConfig()); userInfo != nil {
		klog.Infof("[ApplicationMutatingHandler] add skip user %s", userInfo.Username)
		handler.skipUsers = []string{userInfo.Username}
	}
	server.Register("/mutating-core-oam-dev-v1beta1-applications", &webhook.Admission{Handler: handler})
	klog.InfoS("Application mutating webhook handler registered successfully")
}
