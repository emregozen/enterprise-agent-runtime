{{- define "agent-runtime.runtimeImage" -}}
{{- if .Values.imageRegistry -}}
{{ .Values.imageRegistry }}/{{ .Values.runtimeImage }}
{{- else -}}
{{ .Values.runtimeImage }}
{{- end -}}
{{- end -}}

{{- define "agent-runtime.uiImage" -}}
{{- if .Values.imageRegistry -}}
{{ .Values.imageRegistry }}/{{ .Values.uiImage }}
{{- else -}}
{{ .Values.uiImage }}
{{- end -}}
{{- end -}}

{{- /* OpenShift reads image triggers from the Deployment's own metadata, not the pod template. */ -}}
{{- define "agent-runtime.deploymentAnnotations" -}}
{{- $root := .root -}}
{{- if $root.Values.imageTriggers }}
annotations:
  image.openshift.io/triggers: {{ include "agent-runtime.imageTrigger" (dict "image" .image "namespace" $root.Values.namespace "container" .container) | quote }}
{{- end }}
{{- end -}}

{{- define "agent-runtime.podAnnotations" -}}
{{- $root := .root -}}
{{- if $root.Values.imageBuildId }}
annotations:
  agent-runtime.internal/image-build: {{ $root.Values.imageBuildId | quote }}
{{- end }}
{{- end -}}

{{- define "agent-runtime.imageTrigger" -}}
{{- $parts := splitList ":" .image -}}
{{- $name := index $parts 0 -}}
{{- $tag := "latest" -}}
{{- if gt (len $parts) 1 -}}
{{- $tag = index $parts (sub (len $parts) 1) -}}
{{- end -}}
{{- $path := printf "spec.template.spec.containers[?(@.name==\"%s\")].image" .container -}}
{{- $item := dict "from" (dict "kind" "ImageStreamTag" "name" (printf "%s:%s" $name $tag) "namespace" .namespace) "fieldPath" $path -}}
{{- toJson (list $item) -}}
{{- end -}}

{{- define "agent-runtime.restricted" -}}
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "agent-runtime.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities:
  drop: ["ALL"]
seccompProfile:
  type: RuntimeDefault
{{- end -}}
