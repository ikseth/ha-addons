package maintenance

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type fakeRegistry struct {
	keys    map[string]bool
	strings map[string]string
	lists   map[string][]string
}

func (reader fakeRegistry) KeyExists(path string) (bool, error) { return reader.keys[path], nil }
func (reader fakeRegistry) String(path, name string) (string, error) {
	value, ok := reader.strings[path+"|"+name]
	if !ok {
		return "", fmt.Errorf("missing fake value")
	}
	return value, nil
}
func (reader fakeRegistry) Strings(path, name string) ([]string, error) {
	return reader.lists[path+"|"+name], nil
}
func (reader fakeRegistry) DWORD(string, string) (uint32, error) { return 0, nil }

type fakeSource struct{ registry fakeRegistry }

func (source fakeSource) Registry() winapi.RegistryReader { return source.registry }
func (fakeSource) PowerStatus() (winapi.PowerStatus, error) {
	return winapi.PowerStatus{ACLineStatus: 1, BatteryFlag: 8, BatteryLifePercent: 87}, nil
}
func (fakeSource) Uptime() (time.Duration, error)         { return 10 * time.Second, nil }
func (fakeSource) ShutdownStatus() (bool, *string, error) { return false, nil, nil }

func TestPendingRebootReasonsFromSimulatedRegistry(t *testing.T) {
	reader := fakeRegistry{
		keys:    map[string]bool{windowsUpdateKey: true, sccmKey: true},
		strings: map[string]string{computerNameKey + "|ComputerName": "NEW", activeComputerNameKey + "|ComputerName": "OLD"},
		lists:   map[string][]string{sessionManagerKey + "|PendingFileRenameOperations": {`\??\C:\old`, `\??\C:\new`}},
	}
	reasons, err := PendingRebootReasons(reader)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"windows_update", "pending_file_rename", "computer_rename", "sccm"}
	if fmt.Sprint(reasons) != fmt.Sprint(want) {
		t.Fatalf("reasons=%v, want %v", reasons, want)
	}
}

func TestMaintenancePayload(t *testing.T) {
	source := fakeSource{registry: fakeRegistry{keys: map[string]bool{}, strings: map[string]string{computerNameKey + "|ComputerName": "PC", activeComputerNameKey + "|ComputerName": "PC"}, lists: map[string][]string{}}}
	sensor := New(source)
	sensor.now = func() time.Time { return time.Date(2026, 8, 3, 10, 0, 0, 0, time.UTC) }
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if data["power_source"] != "ac" || data["battery_percent"] != 87 || data["boot_time"] != "2026-08-03T09:59:50Z" {
		t.Fatalf("unexpected payload: %#v", data)
	}
}
