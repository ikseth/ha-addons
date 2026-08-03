package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
)

func testServer(t *testing.T, mutate func(*config.Config)) *Server {
	t.Helper()
	cfg := config.Defaults()
	cfg.API.Token = "01234567890123456789012345678901"
	cfg.TLS.Enabled = false
	cfg.API.BindHost = "127.0.0.1"
	if mutate != nil {
		mutate(&cfg)
	}
	server, err := New(Options{Config: cfg})
	if err != nil {
		t.Fatal(err)
	}
	return server
}

func request(server *Server, method, path, peer, token string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, nil)
	req.RemoteAddr = peer
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	recorder := httptest.NewRecorder()
	server.dispatch(recorder, req)
	return recorder
}

func TestHealthAndVersionContract(t *testing.T) {
	server := testServer(t, nil)
	health := request(server, http.MethodGet, "/health", "192.0.2.1:1000", "")
	if health.Code != http.StatusOK || strings.TrimSpace(health.Body.String()) != `{"status":"ok"}` {
		t.Fatalf("unexpected health response: %d %s", health.Code, health.Body.String())
	}
	unauthorized := request(server, http.MethodGet, "/v1/version", "192.0.2.1:1000", "")
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("version without token returned %d", unauthorized.Code)
	}
	authorized := request(server, http.MethodGet, "/v1/version", "192.0.2.1:1000", "01234567890123456789012345678901")
	var payload map[string]any
	if err := json.Unmarshal(authorized.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if authorized.Code != http.StatusOK || payload["platform"] != "windows" || payload["schema_version"] != "1.1" {
		t.Fatalf("unexpected version response: %d %#v", authorized.Code, payload)
	}
}

func TestAllowedClientsRunsBeforeToken(t *testing.T) {
	server := testServer(t, func(cfg *config.Config) {
		cfg.API.AllowedClients = []string{"192.168.1.0/24"}
	})
	response := request(server, http.MethodGet, "/v1/version", "192.0.2.1:1000", "wrong")
	if response.Code != http.StatusForbidden {
		t.Fatalf("expected allowlist 403 before auth, got %d: %s", response.Code, response.Body.String())
	}
}

func TestUniformErrorsAndBodyLimit(t *testing.T) {
	server := testServer(t, nil)
	req := httptest.NewRequest(http.MethodPost, "/missing", strings.NewReader(strings.Repeat("x", maxRequestBody+1)))
	req.RemoteAddr = "192.0.2.1:1000"
	recorder := httptest.NewRecorder()
	server.dispatch(recorder, req)
	if recorder.Code != http.StatusRequestEntityTooLarge || recorder.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("unexpected oversized response: %d %s", recorder.Code, recorder.Body.String())
	}
	var payload errorResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil || payload.OK || payload.Error == "" {
		t.Fatalf("non-canonical error: err=%v payload=%+v", err, payload)
	}
}
