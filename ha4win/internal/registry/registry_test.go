package registry

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
)

type testSensor struct {
	id      string
	collect func(context.Context) (map[string]any, error)
}

type testActuator struct {
	id       string
	describe func() map[string]any
	execute  func(context.Context, string, map[string]any) (map[string]any, error)
}

func (actuator testActuator) ID() string { return actuator.id }
func (actuator testActuator) Describe() map[string]any {
	return actuator.describe()
}
func (actuator testActuator) Execute(ctx context.Context, action string, params map[string]any) (map[string]any, error) {
	return actuator.execute(ctx, action, params)
}

func TestLoadRegistersPhaseTwoSensors(t *testing.T) {
	cfg := config.Defaults()
	cfg.Modules.SystemInfo.UpdatesEnabled = false
	cfg.Modules.Security.Defender = false
	loaded := Load(cfg, nil)
	ids := loaded.SensorIDs()
	found := map[string]bool{}
	for _, id := range ids {
		found[id] = true
	}
	for _, id := range []string{"system_info", "maintenance", "security"} {
		if !found[id] {
			t.Fatalf("phase two sensor %q not registered: %v", id, ids)
		}
	}
}

type unavailableSensor struct{ testSensor }

func (unavailableSensor) Available() (bool, string) { return false, "missing prerequisite" }

type unavailableActuator struct{ testActuator }

func (unavailableActuator) Available() (bool, string) { return false, "missing prerequisite" }

func (s testSensor) ID() string { return s.id }
func (s testSensor) Collect(ctx context.Context) (map[string]any, error) {
	return s.collect(ctx)
}

func TestRegisterSensorHonorsProbe(t *testing.T) {
	registry := New(time.Second, nil)
	registered := registry.RegisterSensor(unavailableSensor{testSensor{id: "unavailable"}})
	if registered || len(registry.SensorIDs()) != 0 {
		t.Fatalf("unavailable sensor was registered: %v", registry.SensorIDs())
	}
}

func TestRegisterActuatorHonorsProbe(t *testing.T) {
	registry := New(time.Second, nil)
	registered := registry.RegisterActuator(unavailableActuator{testActuator{id: "unavailable"}})
	if registered || len(registry.ActuatorIDs()) != 0 {
		t.Fatalf("unavailable actuator was registered: %v", registry.ActuatorIDs())
	}
}

func TestCollectIsolatesTimeoutAndPanic(t *testing.T) {
	registry := New(20*time.Millisecond, nil)
	registry.RegisterSensor(testSensor{id: "ok", collect: func(context.Context) (map[string]any, error) {
		return map[string]any{"value": true}, nil
	}})
	registry.RegisterSensor(testSensor{id: "slow", collect: func(ctx context.Context) (map[string]any, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}})
	registry.RegisterSensor(testSensor{id: "panic", collect: func(context.Context) (map[string]any, error) {
		panic("broken sensor")
	}})

	started := time.Now()
	results := registry.Collect(context.Background())
	if elapsed := time.Since(started); elapsed > 200*time.Millisecond {
		t.Fatalf("collection took too long: %s", elapsed)
	}
	if !results["ok"].Available || results["ok"].Data["value"] != true {
		t.Fatalf("healthy sensor was not preserved: %+v", results["ok"])
	}
	if results["slow"].Available || results["slow"].Reason != "timeout after 20ms" {
		t.Fatalf("unexpected timeout result: %+v", results["slow"])
	}
	if results["panic"].Available || results["panic"].Reason != "panic: broken sensor" {
		t.Fatalf("unexpected panic result: %+v", results["panic"])
	}
}

func TestActuatorRegistrationCapabilitiesExecutionAndRecovery(t *testing.T) {
	registry := New(time.Second, nil)
	registry.RegisterActuator(testActuator{
		id:       "ok",
		describe: func() map[string]any { return map[string]any{"actions": []string{"run"}} },
		execute: func(_ context.Context, action string, _ map[string]any) (map[string]any, error) {
			return map[string]any{"action": action}, nil
		},
	})
	registry.RegisterActuator(testActuator{
		id:       "panic",
		describe: func() map[string]any { panic("describe failed") },
		execute: func(context.Context, string, map[string]any) (map[string]any, error) {
			panic("execute failed")
		},
	})
	if got := registry.ActuatorIDs(); len(got) != 2 || got[0] != "ok" || got[1] != "panic" {
		t.Fatalf("actuator IDs = %#v", got)
	}
	capabilities := registry.ActuatorCapabilities()
	if capabilities["ok"].(map[string]any)["actions"] == nil || capabilities["panic"].(map[string]any)["available"] != false {
		t.Fatalf("unexpected capabilities: %#v", capabilities)
	}
	result, err := registry.ExecuteActuator(context.Background(), "ok", "run", nil)
	if err != nil || result["action"] != "run" {
		t.Fatalf("execution result=%#v err=%v", result, err)
	}
	if _, err := registry.ExecuteActuator(context.Background(), "panic", "run", nil); !errors.Is(err, ErrActuatorPanic) {
		t.Fatalf("panic execution returned %v", err)
	}
	if _, err := registry.ExecuteActuator(context.Background(), "missing", "run", nil); !errors.Is(err, ErrActuatorNotFound) {
		t.Fatalf("missing execution returned %v", err)
	}
}

func TestLoadOmitsActuatorsInReadonlyMode(t *testing.T) {
	cfg := config.Defaults()
	factory := func([]string, int) Actuator {
		return testActuator{
			id:       "power_manager",
			describe: func() map[string]any { return map[string]any{} },
			execute: func(context.Context, string, map[string]any) (map[string]any, error) {
				return map[string]any{}, nil
			},
		}
	}
	if ids := load(cfg, nil, factory).ActuatorIDs(); len(ids) != 1 || ids[0] != "power_manager" {
		t.Fatalf("writable registry actuator IDs: %#v", ids)
	}
	cfg.Actuators.Power.Enabled = false
	if ids := load(cfg, nil, factory).ActuatorIDs(); len(ids) != 0 {
		t.Fatalf("disabled registry has actuators: %#v", ids)
	}
	cfg.Actuators.Power.Enabled = true
	cfg.ReadonlyMode = true
	if ids := load(cfg, nil, factory).ActuatorIDs(); len(ids) != 0 {
		t.Fatalf("readonly registry has actuators: %#v", ids)
	}
}
