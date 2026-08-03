package services

import (
	"context"
	"testing"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type fakeSource struct {
	services map[string]winapi.WatchedService
}

func (f fakeSource) Service(name string) (winapi.WatchedService, error) {
	return f.services[name], nil
}

func TestNormalizeWatchlist(t *testing.T) {
	actual := NormalizeWatchlist([]string{" Spooler ", "", "spooler", "Print Spooler", "  WSearch"})
	expected := []string{"Spooler", "Print Spooler", "WSearch"}
	if len(actual) != len(expected) {
		t.Fatalf("NormalizeWatchlist()=%v, want %v", actual, expected)
	}
	for index := range expected {
		if actual[index] != expected[index] {
			t.Fatalf("NormalizeWatchlist()=%v, want %v", actual, expected)
		}
	}
}

func TestMissingServicesAreOmittedAndFailureFormulaIsExact(t *testing.T) {
	sensor := New([]string{"good", "failed", "never", "manual", "missing"}, fakeSource{services: map[string]winapi.WatchedService{
		"good":   {Name: "good", Exists: true, Status: "running", StartType: "auto"},
		"failed": {Name: "failed", Exists: true, Status: "stopped", StartType: "auto_delayed", ExitCode: 5},
		"never":  {Name: "never", Exists: true, Status: "stopped", StartType: "auto", ExitCode: 1077},
		"manual": {Name: "manual", Exists: true, Status: "stopped", StartType: "manual", ExitCode: 5},
	}})
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if data["services_total"] != 4 || data["services_active"] != 1 || data["services_failed"] != 1 {
		t.Fatalf("unexpected service summary: %#v", data)
	}
}
