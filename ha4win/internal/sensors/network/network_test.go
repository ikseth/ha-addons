package network

import (
	"context"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type fakeSource struct{ samples [][]winapi.NetworkInterface }

func (f *fakeSource) Interfaces() ([]winapi.NetworkInterface, error) {
	result := f.samples[0]
	if len(f.samples) > 1 {
		f.samples = f.samples[1:]
	}
	return result, nil
}

func TestInterfaceWildcardFiltering(t *testing.T) {
	items := []winapi.NetworkInterface{
		{Alias: "Ethernet", OperStatus: "up", Hardware: true}, {Alias: "Wi-Fi", OperStatus: "up", Hardware: true},
		{Alias: "vEthernet (Default Switch)", OperStatus: "up", Hardware: true}, {Alias: "Loopback", OperStatus: "up", Hardware: true, Loopback: true},
	}
	filtered := filterInterfaces(items, []string{"E*", "Wi-?i"}, []string{"vEthernet*"})
	if len(filtered) != 2 || filtered[0].Alias != "Ethernet" || filtered[1].Alias != "Wi-Fi" {
		t.Fatalf("unexpected filtered interfaces: %+v", filtered)
	}
}

func TestCounterDeltaUsesAbsoluteValueAfterReset(t *testing.T) {
	if value := counterDelta(1000, 25); value != 25 {
		t.Fatalf("counter reset delta=%d, want 25", value)
	}
	if value := counterDelta(1000, 1200); value != 200 {
		t.Fatalf("normal delta=%d, want 200", value)
	}
}

func TestAggregateModes(t *testing.T) {
	sample := []winapi.NetworkInterface{
		{Alias: "Ethernet", OperStatus: "up", RXBytes: 100, TXBytes: 10, Hardware: true},
		{Alias: "Wi-Fi", OperStatus: "up", RXBytes: 200, TXBytes: 20, Hardware: true},
	}
	selected := New([]string{"Ethernet"}, nil, "selected", &fakeSource{samples: [][]winapi.NetworkInterface{sample}})
	all := New([]string{"Ethernet"}, nil, "all", &fakeSource{samples: [][]winapi.NetworkInterface{sample}})
	selected.now = func() time.Time { return time.Unix(1, 0) }
	all.now = selected.now
	selectedData, err := selected.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	allData, err := all.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if selectedData["total_rx_bytes"] != uint64(100) || allData["total_rx_bytes"] != uint64(300) {
		t.Fatalf("unexpected aggregate totals: selected=%v all=%v", selectedData["total_rx_bytes"], allData["total_rx_bytes"])
	}
}

func TestOnlyHardwareInterfacesAreListedAndAggregated(t *testing.T) {
	sample := []winapi.NetworkInterface{
		{Alias: "Ethernet", OperStatus: "up", RXBytes: 100, TXBytes: 10, Hardware: true},
		{Alias: "QoS Packet Scheduler", OperStatus: "up", RXBytes: 100, TXBytes: 10},
		{Alias: "Npcap Packet Driver", OperStatus: "up", RXBytes: 100, TXBytes: 10},
	}
	sensor := New(nil, nil, "all", &fakeSource{samples: [][]winapi.NetworkInterface{sample}})
	sensor.now = func() time.Time { return time.Unix(1, 0) }

	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	interfaces := data["interfaces"].(map[string]any)
	if len(interfaces) != 1 || interfaces["Ethernet"] == nil {
		t.Fatalf("unexpected interfaces: %#v", interfaces)
	}
	if data["total_rx_bytes"] != uint64(100) || data["total_tx_bytes"] != uint64(10) {
		t.Fatalf("filter interfaces were aggregated: %#v", data)
	}
}

func TestInterfaceDeltasNeverGoNegativeAfterReset(t *testing.T) {
	source := &fakeSource{samples: [][]winapi.NetworkInterface{
		{{Alias: "Ethernet", OperStatus: "up", RXBytes: 4096, TXBytes: 2048, Hardware: true}},
		{{Alias: "Ethernet", OperStatus: "up", RXBytes: 1024, TXBytes: 512, Hardware: true}},
	}}
	sensor := New(nil, nil, "selected", source)
	now := time.Unix(1, 0)
	sensor.now = func() time.Time { now = now.Add(time.Second); return now }
	if _, err := sensor.Collect(context.Background()); err != nil {
		t.Fatal(err)
	}
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if data["rx_kib_window"] != 1.0 || data["tx_kib_window"] != 0.5 {
		t.Fatalf("unexpected reset window: %#v", data)
	}
}
