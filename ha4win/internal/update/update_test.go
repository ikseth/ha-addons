package update

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
)

func TestCompareVersionsRejectsDowngradeAndOrdersPrerelease(t *testing.T) {
	tests := []struct {
		left, right string
		want        int
	}{
		{"0.2.0", "0.1.0", 1},
		{"0.2.0-rc.1", "0.2.0", -1},
		{"v1.0.0+build.2", "1.0.0+build.1", 0},
		{"1.0.0-rc.10", "1.0.0-rc.2", 1},
	}
	for _, test := range tests {
		got, err := CompareVersions(test.left, test.right)
		if err != nil || got != test.want {
			t.Fatalf("CompareVersions(%q, %q) = %d, %v; want %d", test.left, test.right, got, err, test.want)
		}
	}
	if _, err := CompareVersions("1.2", "1.2.0"); err == nil {
		t.Fatal("incomplete semantic version was accepted")
	}
}

func TestParseManifestSelectsChannelAndResolvesArchitecture(t *testing.T) {
	data := []byte(`{
  "channels": {
    "stable": {
      "version": "0.2.0",
      "asset_url": "https://example.test/ha4win-0.2.0-windows-{arch}.zip",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "min_windows_build": 14393
    },
    "beta": {
      "version": "0.3.0-rc.1",
      "asset_url": "https://example.test/ha4win-0.3.0-rc.1-windows-{arch}.zip",
      "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
}`)
	entry, err := ParseManifest(data, "beta", "arm64")
	if err != nil {
		t.Fatal(err)
	}
	if entry.Version != "0.3.0-rc.1" || !strings.Contains(entry.AssetURL, "windows-arm64") {
		t.Fatalf("unexpected selected manifest: %+v", entry)
	}
	if _, err := ParseManifest(data, "nightly", "amd64"); err == nil {
		t.Fatal("missing channel was accepted")
	}
	wrongArch := []byte(`{"version":"0.2.0","asset_url":"https://example.test/ha4win-0.2.0-windows-amd64.zip","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`)
	if _, err := ParseManifest(wrongArch, "stable", "arm64"); err == nil {
		t.Fatal("mismatched literal asset architecture was accepted")
	}
}

func TestStateTransitions(t *testing.T) {
	if !CanTransition(StateChecking, StateIdle) || !CanTransition(StateApplying, StateRestarting) || !CanTransition(StateRestarting, StateRollback) {
		t.Fatal("required update state transition is missing")
	}
	if CanTransition(StateIdle, StateRestarting) || CanTransition(StateDisabled, StateApplying) {
		t.Fatal("invalid update state transition was accepted")
	}
}

func TestEvaluatePreflightWithSimulatedChecks(t *testing.T) {
	input := PreflightInput{
		RunningUnderSCM: true, InstallWritable: true, FreeBytes: 300, ArtifactBytes: 100,
		AssetURL: "https://example.test/ha4win-windows-amd64.zip", HostArchitecture: "amd64", AssetArchitecture: "amd64",
		WindowsBuild: 22631, MinWindowsBuild: 14393,
	}
	result := EvaluatePreflight(input)
	if !result.OK || !result.CanApply || result.Reason != nil {
		t.Fatalf("valid preflight was rejected: %+v", result)
	}
	input.ReadonlyMode = true
	result = EvaluatePreflight(input)
	if result.CanApply || result.Reason == nil || !strings.Contains(*result.Reason, "readonly") {
		t.Fatalf("readonly preflight did not block apply: %+v", result)
	}
	input.ReadonlyMode = false
	input.FreeBytes = 299
	result = EvaluatePreflight(input)
	if result.CanApply || result.Reason == nil || !strings.Contains(*result.Reason, "required") {
		t.Fatalf("disk preflight did not enforce 3x: %+v", result)
	}
}

func TestPersistentStateRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "update-state.json")
	now := time.Date(2026, 8, 3, 10, 0, 0, 0, time.UTC)
	state := PersistentState{
		SchemaVersion: 1, OperationID: "operation", Operation: "apply", State: StateApplying,
		InstalledVersion: "0.1.0", TargetVersion: "0.2.0", StagedPath: `/tmp/staging/ha4win.exe`,
		InstallPath: `/tmp/install/ha4win.exe`, PreviousPath: `/tmp/install/ha4win.exe.previous`, ConfigPath: `/tmp/config.json`, StartedAt: now,
	}
	if err := WritePersistentState(path, state); err != nil {
		t.Fatal(err)
	}
	loaded, err := ReadPersistentState(path)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.OperationID != state.OperationID || loaded.TargetVersion != state.TargetVersion || !loaded.StartedAt.Equal(now) {
		t.Fatalf("state round trip changed data: %+v", loaded)
	}
	if _, err := os.Stat(path + ".tmp"); !os.IsNotExist(err) {
		t.Fatalf("temporary state file remains: %v", err)
	}
}

type fakeSystem struct {
	launchExecutable string
	launchArguments  []string
}

func (*fakeSystem) RunningUnderSCM() (bool, error)            { return true, nil }
func (*fakeSystem) DirectoryWritable(string) bool             { return true }
func (*fakeSystem) FreeSpace(string) (uint64, error)          { return 1 << 30, nil }
func (*fakeSystem) WindowsBuild() (uint32, error)             { return 22631, nil }
func (*fakeSystem) PendingReboot() (bool, error)              { return false, nil }
func (*fakeSystem) VerifyAuthenticode(string) (bool, error)   { return true, nil }
func (*fakeSystem) BinaryArchitecture(string) (string, error) { return "amd64", nil }
func (system *fakeSystem) LaunchDetached(executable string, arguments []string) error {
	system.launchExecutable = executable
	system.launchArguments = append([]string(nil), arguments...)
	return nil
}
func (*fakeSystem) TestBinaryVersion(context.Context, string) (string, error) { return "0.2.0", nil }

func TestManagerApplyPreparesVerifiedArtifactAndPersistsOperation(t *testing.T) {
	archive := updateZIP(t, []byte("test executable"))
	digest := sha256.Sum256(archive)
	client := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		var body []byte
		switch r.URL.Path {
		case "/manifest.json":
			if r.URL.Query().Get("ha4win_ts") == "" {
				t.Error("manifest request did not include cache-busting timestamp")
			}
			body, _ = json.Marshal(map[string]any{
				"version": "0.2.0", "asset_url": "https://example.test/ha4win-0.2.0-windows-amd64.zip", "sha256": hex.EncodeToString(digest[:]), "min_windows_build": 14393,
			})
		case "/ha4win-0.2.0-windows-amd64.zip":
			body = archive
		default:
			return &http.Response{StatusCode: http.StatusNotFound, Body: io.NopCloser(strings.NewReader("not found")), Header: make(http.Header)}, nil
		}
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(bytes.NewReader(body)), ContentLength: int64(len(body)), Header: make(http.Header)}, nil
	})}
	directory := t.TempDir()
	installDirectory := filepath.Join(directory, "install")
	if err := os.MkdirAll(installDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	cfg := config.Defaults()
	cfg.Management.RemoteUpdate.Enabled = true
	cfg.Management.RemoteUpdate.ManifestURL = "https://example.test/manifest.json"
	cfg.TLS.Enabled = false
	system := &fakeSystem{}
	manager := NewManager(ManagerOptions{
		Config: cfg, ConfigPath: filepath.Join(directory, "config.json"), InstalledVersion: "0.1.0", Architecture: "amd64",
		InstallPath: filepath.Join(installDirectory, "ha4win.exe"), UpdateDirectory: filepath.Join(directory, "update"), System: system, HTTPClient: client,
	})
	status := manager.Apply(context.Background(), "0.2.0")
	if !status.OK || status.State != StateRestarting || system.launchExecutable == "" {
		t.Fatalf("apply was not handed to detached updater: status=%+v system=%+v", status, system)
	}
	state, err := ReadPersistentState(filepath.Join(directory, "update", "update-state.json"))
	if err != nil {
		t.Fatal(err)
	}
	if state.TargetVersion != "0.2.0" || state.Operation != "apply" || state.StagedPath != system.launchExecutable {
		t.Fatalf("unexpected persisted operation: %+v", state)
	}
}

func TestManagerRollbackDoesNotRequireManifestCheck(t *testing.T) {
	directory := t.TempDir()
	installDirectory := filepath.Join(directory, "install")
	if err := os.MkdirAll(installDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	installPath := filepath.Join(installDirectory, "ha4win.exe")
	if err := os.WriteFile(installPath, []byte("current"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(installPath+".previous", []byte("previous"), 0o700); err != nil {
		t.Fatal(err)
	}
	cfg := config.Defaults()
	cfg.Management.RemoteUpdate.Enabled = true
	cfg.Management.RemoteUpdate.ManifestURL = "https://example.test/manifest.json"
	system := &fakeSystem{}
	manager := NewManager(ManagerOptions{
		Config: cfg, ConfigPath: filepath.Join(directory, "config.json"), InstalledVersion: "0.2.0", Architecture: "amd64",
		InstallPath: installPath, UpdateDirectory: filepath.Join(directory, "update"), System: system,
	})
	status := manager.Rollback(context.Background())
	if !status.OK || status.State != StateRestarting || system.launchExecutable != installPath {
		t.Fatalf("local rollback was not launched without a manifest fetch: status=%+v system=%+v", status, system)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func updateZIP(t *testing.T, executable []byte) []byte {
	t.Helper()
	var output bytes.Buffer
	writer := zip.NewWriter(&output)
	entry, err := writer.Create("ha4win.exe")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := entry.Write(executable); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return output.Bytes()
}

type fakeApplyPlatform struct {
	calls      []string
	moveNumber int
	failMove   int
}

func (platform *fakeApplyPlatform) StopService(time.Duration) error {
	platform.calls = append(platform.calls, "stop")
	return nil
}
func (platform *fakeApplyPlatform) StartService() error {
	platform.calls = append(platform.calls, "start")
	return nil
}
func (platform *fakeApplyPlatform) ReplaceFile(source, destination string) error {
	platform.moveNumber++
	platform.calls = append(platform.calls, "move:"+filepath.Base(source)+"->"+filepath.Base(destination))
	if platform.moveNumber == platform.failMove {
		return errors.New("simulated promotion failure")
	}
	return nil
}

func TestApplierRestoresPreviousWhenPromotionFails(t *testing.T) {
	directory := t.TempDir()
	installDirectory := filepath.Join(directory, "install")
	updateDirectory := filepath.Join(directory, "update")
	stagingDirectory := filepath.Join(updateDirectory, "staging")
	for _, path := range []string{installDirectory, stagingDirectory} {
		if err := os.MkdirAll(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	installPath := filepath.Join(installDirectory, "ha4win.exe")
	stagedPath := filepath.Join(stagingDirectory, "ha4win.exe")
	if err := os.WriteFile(installPath, []byte("old"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stagedPath, []byte("new"), 0o700); err != nil {
		t.Fatal(err)
	}
	statePath := filepath.Join(updateDirectory, "update-state.json")
	state := PersistentState{
		SchemaVersion: 1, OperationID: "operation", Operation: "apply", State: StateApplying,
		InstalledVersion: "0.1.0", TargetVersion: "0.2.0", StagedPath: stagedPath, InstallPath: installPath,
		PreviousPath: installPath + ".previous", ConfigPath: filepath.Join(directory, "config.json"), StartedAt: time.Now(),
	}
	if err := WritePersistentState(statePath, state); err != nil {
		t.Fatal(err)
	}
	lock, err := acquireFileLock(filepath.Join(updateDirectory, "update.lock"), state.OperationID)
	if err != nil {
		t.Fatal(err)
	}
	_ = lock
	platform := &fakeApplyPlatform{failMove: 2}
	err = NewApplier(ApplierOptions{Platform: platform}).Run(statePath)
	if err == nil || !strings.Contains(err.Error(), "promotion failure") {
		t.Fatalf("expected promotion failure, got %v", err)
	}
	want := []string{
		"stop", "move:ha4win.exe->ha4win.exe.previous", "move:ha4win.exe.new->ha4win.exe", "move:ha4win.exe.previous->ha4win.exe", "start",
	}
	if strings.Join(platform.calls, "|") != strings.Join(want, "|") {
		t.Fatalf("unexpected transactional order: got %#v want %#v", platform.calls, want)
	}
	result, err := ReadPersistentState(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if result.Result != "rolled_back" || result.CompletedAt == nil {
		t.Fatalf("rollback result was not persisted: %+v", result)
	}
}
