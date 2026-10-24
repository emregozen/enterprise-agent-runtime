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
