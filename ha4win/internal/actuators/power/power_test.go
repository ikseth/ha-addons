package power

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"
)

type fakeSource struct {
	available         bool
	session           *Session
	hibernate         bool
	pendingReboot     bool
	disconnected      []uint32
	suspended         []bool
	scheduled         []shutdownCall
	aborted           int
	scheduleErr       error
	abortErr          error
	hibernateCheckErr error
}

type shutdownCall struct {
	reboot  bool
	delay   uint32
	force   bool
	message string
}

func (source *fakeSource) Available() (bool, string) {
	if source.available {
		return true, ""
	}
	return false, "unavailable"
}
func (source *fakeSource) ActiveConsoleSession() (*Session, error) { return source.session, nil }
func (source *fakeSource) DisconnectSession(id uint32) error {
	source.disconnected = append(source.disconnected, id)
	return nil
}
func (source *fakeSource) HibernateSupported() (bool, error) {
	return source.hibernate, source.hibernateCheckErr
}
func (source *fakeSource) Suspend(hibernate, _ bool) error {
	source.suspended = append(source.suspended, hibernate)
	return nil
}
func (source *fakeSource) ScheduleShutdown(reboot bool, delay uint32, force bool, message string) error {
	source.scheduled = append(source.scheduled, shutdownCall{reboot: reboot, delay: delay, force: force, message: message})
	return source.scheduleErr
}
func (source *fakeSource) AbortShutdown() error {
	source.aborted++
	return source.abortErr
}
func (source *fakeSource) PendingReboot() (bool, error) { return source.pendingReboot, nil }

func TestAvailableActions(t *testing.T) {
	source := &fakeSource{available: true}
	actuator := New([]string{"lock", "hibernate", "restart", "restart"}, 30, source)
	description := actuator.Describe()
	if got, want := description["allowed_actions"], []string{"lock", "hibernate", "restart"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("allowed actions = %#v, want %#v", got, want)
	}
	if got, want := description["available_actions"], []string{"lock", "restart", "cancel", "status"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("available actions = %#v, want %#v", got, want)
	}
	source.hibernate = true
	if got, want := actuator.Describe()["available_actions"], []string{"lock", "hibernate", "restart", "cancel", "status"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("available actions with hibernation = %#v, want %#v", got, want)
	}
}

func TestDefaultActionsAndNotAllowedRejection(t *testing.T) {
	source := &fakeSource{available: true}
	actuator := New([]string{"lock"}, 30, source)
	if got, want := actuator.Describe()["available_actions"], []string{"lock", "status"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("default available actions = %#v, want %#v", got, want)
	}
	_, err := actuator.Execute(context.Background(), "shutdown", nil)
	if !errors.Is(err, ErrActionNotAllowed) || !strings.Contains(err.Error(), "not allowed") {
		t.Fatalf("shutdown returned %v", err)
	}
	if len(source.scheduled) != 0 {
		t.Fatal("disallowed shutdown reached the source")
	}
}

func TestShutdownParameterParsingAndScheduling(t *testing.T) {
	source := &fakeSource{available: true}
	actuator := New([]string{"restart"}, 30, source)
	actuator.now = func() time.Time { return time.Date(2026, 8, 3, 10, 0, 0, 0, time.UTC) }
	var auditedAction string
	var auditedParams map[string]any
	ctx := WithAudit(context.Background(), func(action string, params map[string]any) {
		auditedAction, auditedParams = action, params
	})
	result, err := actuator.Execute(ctx, "restart", map[string]any{
		"delay_seconds": json.Number("60"), "force": true, "message": "Maintenance",
	})
	if err != nil {
		t.Fatal(err)
	}
	wantCall := shutdownCall{reboot: true, delay: 60, force: true, message: "Maintenance"}
	if len(source.scheduled) != 1 || source.scheduled[0] != wantCall {
		t.Fatalf("shutdown call = %#v, want %#v", source.scheduled, wantCall)
	}
	if auditedAction != "restart" || auditedParams["delay_seconds"] != 60 || auditedParams["force"] != true || auditedParams["message"] != "Maintenance" {
		t.Fatalf("audit action=%q params=%#v", auditedAction, auditedParams)
	}
	if result["effective_at"] != "2026-08-03T10:01:00Z" || result["cancellable"] != true {
		t.Fatalf("unexpected result: %#v", result)
	}
	status, err := actuator.Execute(context.Background(), "status", nil)
	if err != nil || status["shutdown_pending"] != true {
		t.Fatalf("pending status = %#v, err=%v", status, err)
	}
	if _, err := actuator.Execute(context.Background(), "cancel", nil); err != nil {
		t.Fatal(err)
	}
	if source.aborted != 1 {
		t.Fatalf("abort calls = %d", source.aborted)
	}
}

func TestInvalidShutdownParameters(t *testing.T) {
	actuator := New([]string{"shutdown"}, 30, &fakeSource{available: true})
	cases := []map[string]any{
		{"delay_seconds": -1},
		{"delay_seconds": 86401},
		{"delay_seconds": 1.5},
		{"force": "true"},
		{"message": true},
		{"extra": true},
	}
	for _, params := range cases {
		if _, err := actuator.Execute(context.Background(), "shutdown", params); !errors.Is(err, ErrInvalidParameters) {
			t.Errorf("params %#v returned %v", params, err)
		}
	}
}

func TestLockWithoutActiveConsoleSession(t *testing.T) {
	source := &fakeSource{available: true}
	actuator := New([]string{"lock"}, 30, source)
	result, err := actuator.Execute(context.Background(), "lock", nil)
	if err != nil {
		t.Fatal(err)
	}
	if result["method"] != "wts_disconnect" || result["message"] != "no active console session" {
		t.Fatalf("unexpected lock result: %#v", result)
	}
	source.session = &Session{SessionID: 7, User: `PC\user`, State: "active"}
	result, err = actuator.Execute(context.Background(), "lock", nil)
	if err != nil || !reflect.DeepEqual(source.disconnected, []uint32{7}) || result["session_id"] != uint32(7) {
		t.Fatalf("active lock result=%#v disconnected=%#v err=%v", result, source.disconnected, err)
	}
}

func TestHibernateUnsupported(t *testing.T) {
	actuator := New([]string{"hibernate"}, 30, &fakeSource{available: true})
	_, err := actuator.Execute(context.Background(), "hibernate", nil)
	if !errors.Is(err, ErrActionUnavailable) {
		t.Fatalf("hibernate returned %v", err)
	}
}
