package systeminfo

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
	wincom "github.com/ikseth/ha-addons/ha4win/internal/winapi/com"
)

type fakeUpdatesProvider struct {
	name     string
	snapshot wincom.UpdateSnapshot
	err      error
	called   chan struct{}
	scope    string
	block    bool
}

func (provider *fakeUpdatesProvider) Name() string { return provider.name }
func (provider *fakeUpdatesProvider) Check(ctx context.Context, scope string) (wincom.UpdateSnapshot, error) {
	provider.scope = scope
	if provider.called != nil {
		close(provider.called)
	}
	if provider.block {
		<-ctx.Done()
		return wincom.UpdateSnapshot{}, ctx.Err()
	}
	return provider.snapshot, provider.err
}

func TestDisabledUpdatesNeverCallsProvider(t *testing.T) {
	provider := &fakeUpdatesProvider{name: "wua", called: make(chan struct{})}
	cache := newUpdatesCache(UpdatesOptions{Enabled: false, Provider: "wua", ProviderImpl: provider, CheckInterval: time.Hour, Timeout: time.Second, MaxPackages: 25})
	data := cache.data()
	if data["updates_state"] != "disabled" || data["updates_refresh_in_progress"] != false {
		t.Fatalf("unexpected disabled cache: %#v", data)
	}
	select {
	case <-provider.called:
		t.Fatal("disabled provider was called")
	default:
	}
}

func TestDisabledProviderNeverRunsWhenUpdatesAreEnabled(t *testing.T) {
	provider := &fakeUpdatesProvider{name: "disabled", called: make(chan struct{})}
	cache := newUpdatesCache(UpdatesOptions{Enabled: true, Provider: "disabled", ProviderImpl: provider, CheckInterval: time.Hour, Timeout: time.Second, MaxPackages: 25})
	data := cache.data()
	if data["updates_state"] != "disabled" || data["updates_supported"] != false || data["updates_provider"] != "disabled" {
		t.Fatalf("unexpected disabled provider cache: %#v", data)
	}
	select {
	case <-provider.called:
		t.Fatal("disabled provider was called")
	default:
	}
}

func TestUpdatesRefreshAndTruncation(t *testing.T) {
	provider := &fakeUpdatesProvider{name: "wua", snapshot: wincom.UpdateSnapshot{RebootRequired: true, Packages: []wincom.UpdatePackage{
		{Title: "security", KB: "123", SizeBytes: 1048576, IsSecurity: true},
		{Title: "regular", KB: "KB456", SizeBytes: 524288},
	}}}
	cache := newUpdatesCache(UpdatesOptions{Enabled: true, Provider: "wua", ProviderImpl: provider, CheckInterval: time.Hour, Timeout: time.Second, MaxPackages: 1})
	deadline := time.Now().Add(time.Second)
	for cache.data()["updates_state"] == "checking" && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	data := cache.data()
	if data["updates_state"] != "idle" || data["updates_pending_count"] != 2 || data["updates_pending_security_count"] != 1 || data["updates_packages_truncated"] != true {
		t.Fatalf("unexpected cache: %#v", data)
	}
	packages := data["updates_packages"].([]updatePackagePayload)
	if len(packages) != 1 || packages[0].KB != "KB123" {
		t.Fatalf("unexpected packages: %#v", packages)
	}
}

func TestUnsupportedUpdatesStopsWithReason(t *testing.T) {
	provider := &fakeUpdatesProvider{name: "wua", err: unsupportedUpdatesError{reason: "wuauserv is disabled"}}
	cache := newUpdatesCache(UpdatesOptions{Enabled: true, Provider: "wua", ProviderImpl: provider, CheckInterval: time.Millisecond, Timeout: time.Second, MaxPackages: 1})
	deadline := time.Now().Add(time.Second)
	for cache.data()["updates_state"] == "checking" && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	data := cache.data()
	if data["updates_state"] != "unsupported" || data["updates_supported"] != false || data["updates_last_error"] != "wuauserv is disabled" {
		t.Fatalf("unexpected unsupported cache: %#v", data)
	}
}

func TestUpdateErrorState(t *testing.T) {
	provider := &fakeUpdatesProvider{name: "wua", err: errors.New("offline")}
	cache := newUpdatesCache(UpdatesOptions{Enabled: true, Provider: "wua", ProviderImpl: provider, CheckInterval: time.Hour, Timeout: time.Second, MaxPackages: 1})
	deadline := time.Now().Add(time.Second)
	for cache.data()["updates_state"] == "checking" && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if data := cache.data(); data["updates_state"] != "error" || data["updates_last_error"] != "offline" {
		t.Fatalf("unexpected error cache: %#v", data)
	}
}

func TestCollectDoesNotWaitForWUAAndPassesManagedScope(t *testing.T) {
	provider := &fakeUpdatesProvider{name: "wua", called: make(chan struct{}), block: true}
	sensor := NewWithUpdates(fakeSource{information: winapi.WindowsInformation{ProductName: "Windows", CurrentBuild: "1"}}, UpdatesOptions{
		Enabled: true, Provider: "wua", ProviderImpl: provider, SearchScope: "managed",
		CheckInterval: time.Hour, Timeout: 20 * time.Millisecond, MaxPackages: 25,
	})
	<-provider.called
	started := time.Now()
	data, err := sensor.Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if elapsed := time.Since(started); elapsed > 50*time.Millisecond {
		t.Fatalf("Collect waited for WUA: %s", elapsed)
	}
	if data["updates_state"] != "checking" || provider.scope != "managed" {
		t.Fatalf("unexpected cold-cache data: %#v scope=%q", data, provider.scope)
	}
}
