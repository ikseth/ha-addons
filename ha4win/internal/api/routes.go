package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"

	"github.com/ikseth/ha-addons/ha4win/internal/actuators/power"
	"github.com/ikseth/ha-addons/ha4win/internal/registry"
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

func (s *Server) resolveRoute(path string) (route, bool) {
	if static, found := s.routes()[path]; found {
		return static, true
	}
	const prefix = "/v1/actuators/"
	if !strings.HasPrefix(path, prefix) {
		return route{}, false
	}
	parts := strings.Split(strings.TrimPrefix(path, prefix), "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return route{}, false
	}
	actuatorID, action := parts[0], parts[1]
	return route{
		method:  http.MethodPost,
		private: true,
		handler: func(w http.ResponseWriter, r *http.Request) {
			s.executeActuator(w, r, actuatorID, action)
		},
	}, true
}

func (s *Server) executeActuator(w http.ResponseWriter, r *http.Request, actuatorID, action string) {
	params, err := decodeActionParameters(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	executionContext := r.Context()
	if s.logger != nil && mutatesPowerState(actuatorID, action) {
		peer := peerAddress(r.RemoteAddr)
		executionContext = power.WithAudit(executionContext, func(executedAction string, effectiveParams map[string]any) {
			s.logger.AuditActuator(peer, actuatorID, executedAction, effectiveParams)
		})
	}
	result, err := s.registry.ExecuteActuator(executionContext, actuatorID, action, params)
	if err != nil {
		switch {
		case errors.Is(err, registry.ErrActuatorNotFound):
			writeError(w, http.StatusNotFound, err.Error())
		case errors.Is(err, power.ErrActionNotAllowed):
			writeError(w, http.StatusForbidden, err.Error())
		case errors.Is(err, power.ErrActionUnavailable), errors.Is(err, power.ErrInvalidParameters):
			writeError(w, http.StatusBadRequest, err.Error())
		default:
			writeError(w, http.StatusInternalServerError, err.Error())
		}
		return
	}
	if _, exists := result["ok"]; !exists {
		result["ok"] = true
	}
	writeJSON(w, http.StatusOK, result)
}

func decodeActionParameters(r *http.Request) (map[string]any, error) {
	if r.Body == nil || r.Body == http.NoBody || r.ContentLength == 0 {
		return map[string]any{}, nil
	}
	decoder := json.NewDecoder(r.Body)
	decoder.UseNumber()
	var params map[string]any
	if err := decoder.Decode(&params); err != nil {
		return nil, fmt.Errorf("request body must be a JSON object: %w", err)
	}
	if params == nil {
		return nil, fmt.Errorf("request body must be a JSON object")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return nil, fmt.Errorf("request body must contain one JSON object")
		}
		return nil, fmt.Errorf("request body has trailing data: %w", err)
	}
	return params, nil
}

func mutatesPowerState(actuatorID, action string) bool {
	if actuatorID != power.ID {
		return false
	}
	switch action {
	case "lock", "sleep", "hibernate", "restart", "shutdown", "cancel":
		return true
	default:
		return false
	}
}

func peerAddress(remoteAddr string) string {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err == nil {
		return host
	}
	return remoteAddr
}

func (s *Server) capabilities() map[string]any {
	return map[string]any{
		"transport":        transportName(s.cfg.TLS.Enabled),
		"platform":         "windows",
		"sensors":          s.registry.SensorIDs(),
		"actuators":        s.registry.ActuatorIDs(),
		"actuator_details": s.registry.ActuatorCapabilities(),
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
