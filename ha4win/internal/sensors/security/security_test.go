package security

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
	wincom "github.com/ikseth/ha-addons/ha4win/internal/winapi/com"
)

type fakeRegistry struct{ dwords map[string]uint32 }

func (fakeRegistry) KeyExists(string) (bool, error)           { return false, nil }
func (fakeRegistry) String(string, string) (string, error)    { return "", nil }
func (fakeRegistry) Strings(string, string) ([]string, error) { return nil, nil }
func (reader fakeRegistry) DWORD(path, name string) (uint32, error) {
	value, ok := reader.dwords[path+"|"+name]
	if !ok {
		return 0, errors.New("missing fake DWORD")
	}
	return value, nil
}

type fakeSource struct{ registry fakeRegistry }

func (source fakeSource) Registry() winapi.RegistryReader { return source.registry }

type fakeWMI struct {
	defender     wincom.DefenderStatus
	defenderErr  error
	volumes      []wincom.BitLockerVolume
	bitLockerErr error
}

type blockingWMI struct{ started chan struct{} }

func (provider blockingWMI) Defender(ctx context.Context) (wincom.DefenderStatus, error) {
	close(provider.started)
	<-ctx.Done()
	return wincom.DefenderStatus{}, ctx.Err()
}

func (blockingWMI) BitLocker(context.Context) ([]wincom.BitLockerVolume, error) {
	return nil, nil
}

func (provider fakeWMI) Defender(context.Context) (wincom.DefenderStatus, error) {
	return provider.defender, provider.defenderErr
}
func (provider fakeWMI) BitLocker(context.Context) ([]wincom.BitLockerVolume, error) {
	return provider.volumes, provider.bitLockerErr
}

func securityRegistry() fakeRegistry {
	return fakeRegistry{dwords: map[string]uint32{
		domainFirewallKey + "|EnableFirewall": 1, privateFirewallKey + "|EnableFirewall": 0,
		publicFirewallKey + "|EnableFirewall": 1, uacKey + "|EnableLUA": 1,
	}}
}

func TestIndependentDegradationAndIssuesCount(t *testing.T) {
	provider := fakeWMI{defenderErr: errors.New("Defender class unavailable"), volumes: []wincom.BitLockerVolume{{DriveLetter: "C:", ProtectionStatus: 0}}}
	sensor := New(Options{Defender: true, Firewall: true, BitLocker: true, RefreshInterval: time.Hour, Timeout: time.Second, WMI: provider}, fakeSource{securityRegistry()})
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if sensor.defender.get().reason == "Defender class unavailable" && sensor.bitlocker.get().available {
			break
		}
		time.Sleep(time.Millisecond)
	}
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defender := data["defender"].(defenderPayload)
	firewall := data["firewall"].(firewallPayload)
	bitlocker := data["bitlocker"].(bitLockerPayload)
	if defender.Available || !firewall.Available || !bitlocker.Available {
		t.Fatalf("sub-block degradation failed: %#v", data)
	}
	if data["issues_count"] != 2 {
		t.Fatalf("issues_count=%v, want firewall private + unprotected volume", data["issues_count"])
	}
}

func TestDisabledWMIBlocksAndUnknownStatesDoNotCount(t *testing.T) {
	sensor := New(Options{Firewall: true, RefreshInterval: time.Hour}, fakeSource{securityRegistry()})
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if data["issues_count"] != 1 {
		t.Fatalf("disabled blocks counted as issues: %#v", data)
	}
	if data["bitlocker"].(bitLockerPayload).Reason != "module disabled by configuration" {
		t.Fatalf("unexpected disabled block: %#v", data)
	}
}

func TestWMIDateConversion(t *testing.T) {
	if got := parseWMIDate("20260802231400.000000+060"); got != "2026-08-02T22:14:00Z" {
		t.Fatalf("got %q", got)
	}
}

func TestCollectDoesNotWaitForDefenderWMI(t *testing.T) {
	provider := blockingWMI{started: make(chan struct{})}
	sensor := New(Options{Defender: true, Firewall: true, RefreshInterval: time.Hour, Timeout: 20 * time.Millisecond, WMI: provider}, fakeSource{securityRegistry()})
	<-provider.started
	started := time.Now()
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if elapsed := time.Since(started); elapsed > 50*time.Millisecond {
		t.Fatalf("Collect waited for WMI: %s", elapsed)
	}
	if data["defender"].(defenderPayload).Reason != "initial refresh in progress" {
		t.Fatalf("unexpected cold-cache payload: %#v", data)
	}
}

func TestSecuritySubBlockJSONKeepsExplicitFalseOnlyWhenAvailable(t *testing.T) {
	available, err := json.Marshal(defenderPayload{Available: true, AntivirusEnabled: false, RealtimeProtectionEnabled: false})
	if err != nil {
		t.Fatal(err)
	}
	text := string(available)
	for _, field := range []string{`"antivirus_enabled":false`, `"realtime_protection_enabled":false`} {
		if !strings.Contains(text, field) {
			t.Fatalf("available Defender payload omitted %s: %s", field, text)
		}
	}
	unavailable, err := json.Marshal(defenderPayload{Reason: "not installed"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(unavailable), "antivirus_enabled") {
		t.Fatalf("unavailable Defender payload contains unknown protection values: %s", unavailable)
	}
}
