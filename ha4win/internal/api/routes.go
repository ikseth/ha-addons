package api

import (
	"net/http"

	"github.com/ikseth/ha-addons/ha4win/internal/version"
)

type route struct {
	method  string
	private bool
	handler http.HandlerFunc
}

func (s *Server) routes() map[string]route {
	return map[string]route{
		"/health": {
			method: http.MethodGet,
			handler: func(w http.ResponseWriter, _ *http.Request) {
				writeJSON(w, http.StatusOK, struct {
					Status string `json:"status"`
				}{Status: "ok"})
			},
		},
		"/v1/version": {
			method:  http.MethodGet,
			private: true,
			handler: func(w http.ResponseWriter, _ *http.Request) {
				writeJSON(w, http.StatusOK, version.Current())
			},
		},
		"/v1/capabilities": {
			method:  http.MethodGet,
			private: true,
			handler: func(w http.ResponseWriter, _ *http.Request) {
				writeJSON(w, http.StatusOK, s.capabilities())
			},
		},
		"/v1/sensors": {
			method:  http.MethodGet,
			private: true,
			handler: func(w http.ResponseWriter, r *http.Request) {
				writeJSON(w, http.StatusOK, s.registry.Collect(r.Context()))
			},
		},
	}
}

func (s *Server) capabilities() map[string]any {
	return map[string]any{
		"transport":        transportName(s.cfg.TLS.Enabled),
		"platform":         "windows",
		"sensors":          s.registry.SensorIDs(),
		"actuators":        []string{},
		"actuator_details": map[string]any{},
		"management": map[string]any{
			"remote_update": map[string]any{
				"enabled": false, "readonly_mode": s.cfg.ReadonlyMode,
				"allow_in_readonly": s.cfg.Management.RemoteUpdate.AllowInReadonly,
				"channel":           s.cfg.Management.RemoteUpdate.Channel,
			},
		},
	}
}

func transportName(tls bool) string {
	if tls {
		return "https"
	}
	return "http"
}
