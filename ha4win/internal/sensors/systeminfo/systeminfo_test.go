package systeminfo

import (
	"context"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type fakeSource struct{ information winapi.WindowsInformation }

func (f fakeSource) WindowsInformation() (winapi.WindowsInformation, error) {
	return f.information, nil
}

func TestPhaseOnePayloadOmitsUpdatesAndCorrectsWindowsElevenName(t *testing.T) {
	installDate := time.Date(2024, 2, 11, 9, 31, 0, 0, time.UTC)
	sensor := New(fakeSource{information: winapi.WindowsInformation{
		Hostname: "PC", ProductName: "Windows 10 Pro", DisplayVersion: "23H2", CurrentBuild: "22631",
		Major: 10, BuildNumber: 22631, UBR: 4169, InstallDate: installDate,
		Uptime: 10 * time.Second, Domain: "WORKGROUP", DomainJoined: false,
	}})
	sensor.now = func() time.Time { return time.Date(2026, 8, 3, 10, 0, 0, 0, time.UTC) }
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if data["edition"] != "Windows 11 Pro" || data["build"] != "22631.4169" {
		t.Fatalf("unexpected Windows identity: %#v", data)
	}
	for key := range data {
		if len(key) >= len("updates_") && key[:len("updates_")] == "updates_" {
			t.Fatalf("phase one payload contains %q", key)
		}
	}
}
