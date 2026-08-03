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
	}
}
