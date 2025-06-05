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
	"encoding/json"
	"fmt"
	"net/http"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/oam-dev/kubevela/apis/core.oam.dev/common"
	"github.com/oam-dev/kubevela/apis/core.oam.dev/v1beta1"
	"github.com/oam-dev/kubevela/apis/types"
	controller "github.com/oam-dev/kubevela/pkg/controller/core.oam.dev"
	"github.com/oam-dev/kubevela/pkg/oam/util"
)

// MutatingHandler handles ComponentDefinition
type MutatingHandler struct {
	Client client.Client
	// Decoder decodes objects
	Decoder *admission.Decoder
	// AutoGenWorkloadDef indicates whether create workloadDef which componentDef refers to
	AutoGenWorkloadDef bool
}

var _ admission.Handler = &MutatingHandler{}

// Handle handles admission requests.
func (h *MutatingHandler) Handle(_ context.Context, req admission.Request) admission.Response {
	klog.InfoS("Starting mutation for ComponentDefinition",
		"resource", req.Resource.Resource, "namespace", req.Namespace, "name", req.Name, "operation", req.Operation, "uid", req.UID)
	obj := &v1beta1.ComponentDefinition{}

	err := h.Decoder.Decode(req, obj)
	if err != nil {
		klog.ErrorS(err, "Failed to decode ComponentDefinition from request", "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}
	// mutate the object
	if err := h.Mutate(obj); err != nil {
		klog.ErrorS(err, "Failed to mutate the componentDefinition", "namespace", obj.Namespace, "name", obj.Name, "uid", req.UID)
		return admission.Errored(http.StatusBadRequest, err)
	}
	klog.InfoS("Successfully mutated ComponentDefinition", "namespace", obj.Namespace, "name", obj.Name, "uid", req.UID)

	marshalled, err := json.Marshal(obj)
	if err != nil {
		klog.ErrorS(err, "Failed to marshal mutated ComponentDefinition", "namespace", obj.Namespace, "name", obj.Name, "uid", req.UID)
		return admission.Errored(http.StatusInternalServerError, err)
	}

	resp := admission.PatchResponseFromRaw(req.AdmissionRequest.Object.Raw, marshalled)
	if len(resp.Patches) > 0 {
		klog.InfoS("Admitting ComponentDefinition with patches",
			"namespace", obj.Namespace, "name", obj.Name, "uid", req.UID, "patches", util.JSONMarshal(resp.Patches))
	} else {
		klog.InfoS("Admitting ComponentDefinition without patches", "namespace", obj.Namespace, "name", obj.Name, "uid", req.UID)
	}
	return resp
}

// Mutate sets all the default value for the ComponentDefinition
func (h *MutatingHandler) Mutate(obj *v1beta1.ComponentDefinition) error {
	klog.InfoS("Mutating ComponentDefinition spec", "namespace", obj.Namespace, "name", obj.Name)

	// If the Type field is not empty, it means that ComponentDefinition refers to an existing WorkloadDefinition
	if obj.Spec.Workload.Type != types.AutoDetectWorkloadDefinition && (obj.Spec.Workload.Type != "" && obj.Spec.Workload.Definition == (common.WorkloadGVK{})) {
		klog.V(1).InfoS("ComponentDefinition references an existing WorkloadDefinition by type", "namespace", obj.Namespace, "name", obj.Name, "workloadType", obj.Spec.Workload.Type)
		workloadDef := new(v1beta1.WorkloadDefinition)
		err := h.Client.Get(context.TODO(), client.ObjectKey{Name: obj.Spec.Workload.Type, Namespace: obj.Namespace}, workloadDef)
		if err != nil {
			klog.ErrorS(err, "Failed to get referenced WorkloadDefinition by type", "namespace", obj.Namespace, "name", obj.Name, "workloadType", obj.Spec.Workload.Type)
			return err
		}
		klog.V(1).InfoS("Successfully fetched referenced WorkloadDefinition by type", "namespace", obj.Namespace, "name", obj.Name, "workloadType", obj.Spec.Workload.Type)
		return nil
	}

	if obj.Spec.Workload.Definition != (common.WorkloadGVK{}) {
		klog.V(1).InfoS("ComponentDefinition has workload definition specified", "namespace", obj.Namespace, "name", obj.Name, "workloadDefinitionGVK", obj.Spec.Workload.Definition)
		// If only Definition field exists, fill Type field according to Definition.
		defRef, err := util.ConvertWorkloadGVK2Definition(h.Client.RESTMapper(), obj.Spec.Workload.Definition)
		if err != nil {
			klog.ErrorS(err, "Failed to convert workload GVK to definition reference", "namespace", obj.Namespace, "name", obj.Name, "workloadDefinitionGVK", obj.Spec.Workload.Definition)
			return err
		}
		klog.V(1).InfoS("Successfully converted workload GVK to definition reference", "namespace", obj.Namespace, "name", obj.Name, "defRefName", defRef.Name)

		if obj.Spec.Workload.Type == "" {
			klog.V(1).InfoS("Workload type is empty, setting from definition reference", "namespace", obj.Namespace, "name", obj.Name, "defRefName", defRef.Name)
			obj.Spec.Workload.Type = defRef.Name
		}

		workloadDef := new(v1beta1.WorkloadDefinition)
		err = h.Client.Get(context.TODO(), client.ObjectKey{Name: defRef.Name, Namespace: obj.Namespace}, workloadDef)
		if err != nil {
			if apierrors.IsNotFound(err) {
				klog.InfoS("Referenced WorkloadDefinition not found", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
				// Create workloadDefinition which componentDefinition refers to
				if h.AutoGenWorkloadDef {
					klog.InfoS("AutoGenWorkloadDef is enabled, creating WorkloadDefinition", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
					workloadDef.SetName(defRef.Name)
					workloadDef.SetNamespace(obj.Namespace)
					workloadDef.Spec.Reference = defRef
					createErr := h.Client.Create(context.TODO(), workloadDef)
					if createErr != nil {
						klog.ErrorS(createErr, "Failed to auto-generate WorkloadDefinition", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
						return createErr
					}
					klog.InfoS("Successfully auto-generated WorkloadDefinition", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
					return nil
				}
				klog.InfoS("AutoGenWorkloadDef is disabled, WorkloadDefinition must exist", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
				return fmt.Errorf("workloadDefinition %s referenced by componentDefinition is not found, please create the workloadDefinition first", defRef.Name)
			}
			klog.ErrorS(err, "Failed to get referenced WorkloadDefinition by definition reference", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
			return err
		}
		klog.V(1).InfoS("Successfully fetched referenced WorkloadDefinition by definition reference", "namespace", obj.Namespace, "name", obj.Name, "workloadDefName", defRef.Name)
		return nil
	}

	if obj.Spec.Workload.Type == "" {
		klog.V(1).InfoS("Workload type is empty and no definition specified, setting type to AutoDetectWorkloadDefinition", "namespace", obj.Namespace, "name", obj.Name)
		obj.Spec.Workload.Type = types.AutoDetectWorkloadDefinition
	}
	klog.InfoS("Finished mutating ComponentDefinition spec", "namespace", obj.Namespace, "name", obj.Name)
	return nil
}

// RegisterMutatingHandler will register component mutation handler to the webhook
func RegisterMutatingHandler(mgr manager.Manager, args controller.Args) {
	klog.InfoS("Registering ComponentDefinition mutating webhook handler", "path", "/mutating-core-oam-dev-v1beta1-componentdefinitions", "autoGenWorkloadDef", args.AutoGenWorkloadDefinition)
	server := mgr.GetWebhookServer()
	server.Register("/mutating-core-oam-dev-v1beta1-componentdefinitions", &webhook.Admission{
		Handler: &MutatingHandler{
			Client:             mgr.GetClient(),
			Decoder:            admission.NewDecoder(mgr.GetScheme()),
			AutoGenWorkloadDef: args.AutoGenWorkloadDefinition,
		},
	})
	klog.InfoS("ComponentDefinition mutating webhook handler registered successfully")
}
