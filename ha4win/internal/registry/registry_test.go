package registry

import (
	"context"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
)

type testSensor struct {
	id      string
	collect func(context.Context) (map[string]any, error)
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
