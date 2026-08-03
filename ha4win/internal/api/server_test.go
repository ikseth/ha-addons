package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/actuators/power"
	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/registry"
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

func TestSensorsAndCapabilitiesContract(t *testing.T) {
	cfg := config.Defaults()
	cfg.API.Token = "01234567890123456789012345678901"
	cfg.TLS.Enabled = false
	cfg.API.BindHost = "127.0.0.1"
	modules := registry.New(time.Second, nil)
	modules.RegisterSensor(apiTestSensor{})
	server, err := New(Options{Config: cfg, Registry: modules})
	if err != nil {
		t.Fatal(err)
	}
	sensors := request(server, http.MethodGet, "/v1/sensors", "192.0.2.1:1000", cfg.API.Token)
	var sensorPayload map[string]registry.SensorResult
	if err := json.Unmarshal(sensors.Body.Bytes(), &sensorPayload); err != nil {
		t.Fatal(err)
	}
	if sensors.Code != http.StatusOK || !sensorPayload["sample"].Enabled || !sensorPayload["sample"].Available {
		t.Fatalf("unexpected sensor response: %d %#v", sensors.Code, sensorPayload)
	}
	capabilities := request(server, http.MethodGet, "/v1/capabilities", "192.0.2.1:1000", cfg.API.Token)
	var capabilityPayload map[string]any
	if err := json.Unmarshal(capabilities.Body.Bytes(), &capabilityPayload); err != nil {
		t.Fatal(err)
	}
	if capabilities.Code != http.StatusOK || capabilityPayload["platform"] != "windows" || capabilityPayload["transport"] != "http" {
		t.Fatalf("unexpected capabilities response: %d %#v", capabilities.Code, capabilityPayload)
	}
}

type apiTestSensor struct{}

func (apiTestSensor) ID() string { return "sample" }
func (apiTestSensor) Collect(context.Context) (map[string]any, error) {
	return map[string]any{"value": 1}, nil
}

type apiTestActuator struct{}

func (apiTestActuator) ID() string { return "sample_actuator" }
func (apiTestActuator) Describe() map[string]any {
	return map[string]any{"actions": []string{"run"}, "available_actions": []string{"run"}}
}
func (apiTestActuator) Execute(_ context.Context, action string, params map[string]any) (map[string]any, error) {
	return map[string]any{"action": action, "value": params["value"]}, nil
}

type apiTestLogger struct {
	audits []string
}

type apiPowerSource struct{}

func (apiPowerSource) Available() (bool, string) { return true, "" }
func (apiPowerSource) ActiveConsoleSession() (*power.Session, error) {
	return &power.Session{SessionID: 1, State: "active"}, nil
}
func (apiPowerSource) DisconnectSession(uint32) error                    { return nil }
func (apiPowerSource) HibernateSupported() (bool, error)                 { return false, nil }
func (apiPowerSource) Suspend(bool, bool) error                          { return nil }
func (apiPowerSource) ScheduleShutdown(bool, uint32, bool, string) error { return nil }
func (apiPowerSource) AbortShutdown() error                              { return nil }
func (apiPowerSource) PendingReboot() (bool, error)                      { return false, nil }

func (*apiTestLogger) Info(string)                           {}
func (*apiTestLogger) Warning(string)                        {}
func (*apiTestLogger) Error(string)                          {}
func (*apiTestLogger) AuditRejection(string, string, string) {}
func (logger *apiTestLogger) AuditActuator(peer, actuator, action string, _ map[string]any) {
	logger.audits = append(logger.audits, fmt.Sprintf("%s:%s:%s", peer, actuator, action))
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

func TestUpdateEndpointsReplacePhaseZeroStubs(t *testing.T) {
	server := testServer(t, nil)
	token := "01234567890123456789012345678901"
	status := request(server, http.MethodGet, "/v1/update/status", "192.0.2.1:1000", token)
	var statusPayload map[string]any
	if err := json.Unmarshal(status.Body.Bytes(), &statusPayload); err != nil {
		t.Fatal(err)
	}
	if status.Code != http.StatusOK || statusPayload["state"] != "disabled" || statusPayload["supports_apply"] != false {
		t.Fatalf("unexpected disabled update status: %d %#v", status.Code, statusPayload)
	}
	check := request(server, http.MethodPost, "/v1/update/check", "192.0.2.1:1000", token)
	var checkPayload map[string]any
	if err := json.Unmarshal(check.Body.Bytes(), &checkPayload); err != nil {
		t.Fatal(err)
	}
	if check.Code != http.StatusOK || checkPayload["ok"] != false {
		t.Fatalf("disabled check did not return a business error: %d %#v", check.Code, checkPayload)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/update/apply", strings.NewReader(`{"target_version":42}`))
	req.RemoteAddr = "192.0.2.1:1000"
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	server.dispatch(recorder, req)
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("invalid update apply body returned %d: %s", recorder.Code, recorder.Body.String())
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

func TestActuatorEndpointAndCapabilities(t *testing.T) {
	cfg := config.Defaults()
	cfg.API.Token = "01234567890123456789012345678901"
	cfg.TLS.Enabled = false
	cfg.API.BindHost = "127.0.0.1"
	modules := registry.New(time.Second, nil)
	modules.RegisterActuator(apiTestActuator{})
	server, err := New(Options{Config: cfg, Registry: modules})
	if err != nil {
		t.Fatal(err)
	}
	unauthorized := request(server, http.MethodPost, "/v1/actuators/sample_actuator/run", "192.0.2.1:1000", "")
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("actuator without token returned %d", unauthorized.Code)
	}

	capabilities := request(server, http.MethodGet, "/v1/capabilities", "192.0.2.1:1000", cfg.API.Token)
	var capabilityPayload struct {
		Actuators       []string                  `json:"actuators"`
		ActuatorDetails map[string]map[string]any `json:"actuator_details"`
	}
	if err := json.Unmarshal(capabilities.Body.Bytes(), &capabilityPayload); err != nil {
		t.Fatal(err)
	}
	if len(capabilityPayload.Actuators) != 1 || capabilityPayload.Actuators[0] != "sample_actuator" || capabilityPayload.ActuatorDetails["sample_actuator"] == nil {
		t.Fatalf("unexpected capabilities: %#v", capabilityPayload)
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/actuators/sample_actuator/run", strings.NewReader(`{"value":42}`))
	req.RemoteAddr = "192.0.2.1:1000"
	req.Header.Set("Authorization", "Bearer "+cfg.API.Token)
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	server.dispatch(recorder, req)
	var result map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if recorder.Code != http.StatusOK || result["ok"] != true || result["action"] != "run" || result["value"] != float64(42) {
		t.Fatalf("unexpected actuator result: %d %#v", recorder.Code, result)
	}
}

func TestPowerActuatorAuditUsesPeerIP(t *testing.T) {
	cfg := config.Defaults()
	cfg.API.Token = "01234567890123456789012345678901"
	cfg.TLS.Enabled = false
	cfg.API.BindHost = "127.0.0.1"
	modules := registry.New(time.Second, nil)
	modules.RegisterActuator(power.New([]string{"lock"}, 30, apiPowerSource{}))
	logger := &apiTestLogger{}
	server, err := New(Options{Config: cfg, Registry: modules, Logger: logger})
	if err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/actuators/power_manager/lock", nil)
	req.RemoteAddr = "[2001:db8::1]:1234"
	req.Header.Set("Authorization", "Bearer "+cfg.API.Token)
	recorder := httptest.NewRecorder()
	server.dispatch(recorder, req)
	if recorder.Code != http.StatusOK || len(logger.audits) != 1 || logger.audits[0] != "2001:db8::1:power_manager:lock" {
		t.Fatalf("response=%d audits=%#v", recorder.Code, logger.audits)
	}
}
