package update

import (
	"archive/zip"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/version"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

const maxAssetSize = 64 * 1024 * 1024

type Logger interface {
	Info(string)
	Warning(string)
	Error(string)
}

type ManagerOptions struct {
	Config           config.Config
	ConfigPath       string
	InstalledVersion string
	Architecture     string
	InstallPath      string
	UpdateDirectory  string
	System           System
	HTTPClient       *http.Client
	Logger           Logger
	Now              func() time.Time
}

type Manager struct {
	mu               sync.Mutex
	cfg              config.Config
	configPath       string
	installedVersion string
	architecture     string
	installPath      string
	previousPath     string
	updateDirectory  string
	statePath        string
	lockPath         string
	system           System
	client           *http.Client
	logger           Logger
	now              func() time.Time
	lastCheck        time.Time
	manifest         *ManifestEntry
	status           Status
	ownedLock        bool
	persistentError  bool
}

func NewManager(options ManagerOptions) *Manager {
	if options.InstalledVersion == "" {
		options.InstalledVersion = version.Version
	}
	if options.Architecture == "" {
		options.Architecture = runtime.GOARCH
	}
	if options.InstallPath == "" {
		options.InstallPath = winapi.InstalledExecutable
	}
	if options.UpdateDirectory == "" {
		options.UpdateDirectory = filepath.Join(winapi.DataDirectory, "update")
	}
	if options.System == nil {
		options.System = NewNativeSystem()
	}
	if options.HTTPClient == nil {
		options.HTTPClient = &http.Client{}
	}
	if options.Now == nil {
		options.Now = time.Now
	}
	manager := &Manager{
		cfg: options.Config, configPath: options.ConfigPath, installedVersion: options.InstalledVersion,
		architecture: options.Architecture, installPath: options.InstallPath, previousPath: options.InstallPath + ".previous",
		updateDirectory: options.UpdateDirectory, statePath: filepath.Join(options.UpdateDirectory, "update-state.json"),
		lockPath: filepath.Join(options.UpdateDirectory, "update.lock"), system: options.System, client: options.HTTPClient,
		logger: options.Logger, now: options.Now,
	}
	manager.status = Status{
		OK: true, Supported: runtime.GOOS == "windows", Enabled: options.Config.Management.RemoteUpdate.Enabled,
		ReadonlyMode: options.Config.ReadonlyMode, AllowInReadonly: options.Config.Management.RemoteUpdate.AllowInReadonly,
		State: StateIdle, InstalledVersion: options.InstalledVersion, Channel: options.Config.Management.RemoteUpdate.Channel,
		ManifestURL: options.Config.Management.RemoteUpdate.ManifestURL, Preflight: Preflight{Checks: []PreflightCheck{}},
	}
	if !manager.status.Enabled {
		manager.status.State = StateDisabled
	}
	manager.loadPreviousOutcome()
	manager.refreshRollbackVersion()
	manager.refreshPreflightLocked(0)
	return manager
}

func (manager *Manager) Status(ctx context.Context) Status {
	manager.mu.Lock()
	manager.reconcilePersistentOutcomeLocked()
	shouldCheck := manager.status.Enabled && (manager.status.State == StateIdle || manager.status.State == StateError) && !manager.operationInProgressLocked() &&
		(manager.lastCheck.IsZero() || manager.now().Sub(manager.lastCheck) >= time.Duration(manager.cfg.Management.RemoteUpdate.CheckIntervalSec)*time.Second)
	manager.mu.Unlock()
	if shouldCheck {
		return manager.Check(ctx)
	}
	manager.mu.Lock()
	defer manager.mu.Unlock()
	manager.refreshPreflightLocked(0)
	return manager.status
}

func (manager *Manager) Check(ctx context.Context) Status {
	manager.mu.Lock()
	if !manager.status.Enabled {
		status := manager.failLocked("remote update disabled by configuration", StateDisabled)
		manager.mu.Unlock()
		return status
	}
	if manager.operationInProgressLocked() {
		status := manager.failLocked("another update is already in progress", StateError)
		manager.mu.Unlock()
		return status
	}
	manager.transitionLocked(StateChecking)
	manager.status.OK = true
	manager.status.Error = nil
	manager.mu.Unlock()

	timeout := time.Duration(manager.cfg.Management.RemoteUpdate.CheckTimeoutSec) * time.Second
	checkContext, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	entry, err := FetchManifest(checkContext, manager.client, manager.cfg.Management.RemoteUpdate.ManifestURL,
		manager.cfg.Management.RemoteUpdate.Channel, manager.architecture, manager.now())

	manager.mu.Lock()
	defer manager.mu.Unlock()
	manager.lastCheck = manager.now()
	checkedAt := manager.now().UTC()
	manager.status.LastCheckedAt = &checkedAt
	if err != nil {
		return manager.failLocked(err.Error(), StateError)
	}
	manager.manifest = &entry
	manager.status.TargetVersion = stringPointer(entry.Version)
	manager.status.ChangelogURL = optionalString(entry.ChangelogURL)
	manager.status.AssetURL = optionalString(entry.AssetURL)
	manager.status.AssetSHA256 = optionalString(strings.ToLower(entry.SHA256))
	comparison, err := CompareVersions(entry.Version, manager.installedVersion)
	if err != nil {
		return manager.failLocked(err.Error(), StateError)
	}
	manager.status.UpdateAvailable = comparison > 0
	manager.transitionLocked(StateIdle)
	manager.status.OK = true
	manager.status.Error = nil
	if !manager.persistentError {
		manager.status.LastError = nil
	}
	manager.refreshPreflightLocked(0)
	if entry.MinWindowsBuild > 0 {
		build, buildErr := manager.system.WindowsBuild()
		if buildErr != nil || build < entry.MinWindowsBuild {
			manager.status.UpdateAvailable = false
		}
	}
	return manager.status
}

func (manager *Manager) Apply(ctx context.Context, requestedVersion string) Status {
	checked := manager.Check(ctx)
	if !checked.OK {
		return checked
	}
	manager.mu.Lock()
	if manager.manifest == nil {
		status := manager.failLocked("manifest has not been checked", StateError)
		manager.mu.Unlock()
		return status
	}
	entry := *manager.manifest
	if requestedVersion != "" && requestedVersion != entry.Version {
		status := manager.failLocked(fmt.Sprintf("target_version %q does not match current manifest version %q", requestedVersion, entry.Version), StateError)
		manager.mu.Unlock()
		return status
	}
	comparison, err := CompareVersions(entry.Version, manager.installedVersion)
	if err != nil || comparison <= 0 || !manager.status.UpdateAvailable {
		status := manager.failLocked("target version is not newer than installed version", StateError)
		manager.mu.Unlock()
		return status
	}
	manager.refreshPreflightLocked(0)
	if !manager.status.Preflight.CanApply {
		reason := "preflight failed for remote apply"
		if manager.status.Preflight.Reason != nil {
			reason = *manager.status.Preflight.Reason
		}
		status := manager.failLocked(reason, StateError)
		manager.mu.Unlock()
		return status
	}
	operationID, err := randomOperationID()
	if err != nil {
		status := manager.failLocked(err.Error(), StateError)
		manager.mu.Unlock()
		return status
	}
	lock, err := acquireFileLock(manager.lockPath, operationID)
	if err != nil {
		status := manager.failLocked(err.Error(), StateError)
		manager.mu.Unlock()
		return status
	}
	manager.ownedLock = true
	manager.transitionLocked(StateDownloading)
	manager.mu.Unlock()

	stagedPath, artifactBytes, prepareErr := manager.prepareArtifact(ctx, entry)
	if prepareErr != nil {
		lock.Release()
		manager.mu.Lock()
		manager.ownedLock = false
		status := manager.failLocked(prepareErr.Error(), StateError)
		manager.mu.Unlock()
		return status
	}
	manager.mu.Lock()
	manager.refreshPreflightLocked(artifactBytes)
	if !manager.status.Preflight.CanApply {
		reason := *manager.status.Preflight.Reason
		lock.Release()
		manager.ownedLock = false
		status := manager.failLocked(reason, StateError)
		manager.mu.Unlock()
		return status
	}
	manager.transitionLocked(StateApplying)
	state := PersistentState{
		SchemaVersion: 1, OperationID: operationID, Operation: "apply", State: StateApplying,
		InstalledVersion: manager.installedVersion, TargetVersion: entry.Version, StagedPath: stagedPath,
		InstallPath: manager.installPath, PreviousPath: manager.previousPath, ConfigPath: manager.configPath,
		StartedAt: manager.now().UTC(),
	}
	if err := WritePersistentState(manager.statePath, state); err != nil {
		lock.Release()
		manager.ownedLock = false
		status := manager.failLocked(err.Error(), StateError)
		manager.mu.Unlock()
		return status
	}
	arguments := []string{"update", "apply", "--from-service", "--state", manager.statePath}
	if err := manager.system.LaunchDetached(stagedPath, arguments); err != nil {
		lock.Release()
		manager.ownedLock = false
		status := manager.failLocked(err.Error(), StateError)
		manager.mu.Unlock()
		return status
	}
	manager.transitionLocked(StateRestarting)
	manager.status.OK = true
	manager.status.Error = nil
	status := manager.status
	manager.mu.Unlock()
	manager.logInfo("detached updater launched for version " + entry.Version)
	return status
}

func (manager *Manager) Rollback(_ context.Context) Status {
	manager.mu.Lock()
	defer manager.mu.Unlock()
	if !manager.status.Enabled {
		return manager.failLocked("remote update disabled by configuration", StateDisabled)
	}
	manager.refreshRollbackVersion()
	if manager.status.RollbackVersion == nil {
		return manager.failLocked("no previous version available", StateError)
	}
	rollbackPreflight := manager.rollbackPreflightLocked()
	if !rollbackPreflight.CanApply {
		reason := "preflight failed for rollback"
		if rollbackPreflight.Reason != nil {
			reason = *rollbackPreflight.Reason
		}
		return manager.failLocked(reason, StateError)
	}
	operationID, err := randomOperationID()
	if err != nil {
		return manager.failLocked(err.Error(), StateError)
	}
	lock, err := acquireFileLock(manager.lockPath, operationID)
	if err != nil {
		return manager.failLocked(err.Error(), StateError)
	}
	manager.ownedLock = true
	manager.transitionLocked(StateRollback)
	state := PersistentState{
		SchemaVersion: 1, OperationID: operationID, Operation: "rollback", State: StateRollback,
		InstalledVersion: manager.installedVersion, TargetVersion: *manager.status.RollbackVersion,
		StagedPath: manager.previousPath, InstallPath: manager.installPath, PreviousPath: manager.previousPath,
		ConfigPath: manager.configPath, StartedAt: manager.now().UTC(),
	}
	if err := WritePersistentState(manager.statePath, state); err != nil {
		lock.Release()
		manager.ownedLock = false
		return manager.failLocked(err.Error(), StateError)
	}
	arguments := []string{"update", "rollback", "--from-service", "--state", manager.statePath}
	if err := manager.system.LaunchDetached(manager.installPath, arguments); err != nil {
		lock.Release()
		manager.ownedLock = false
		return manager.failLocked(err.Error(), StateError)
	}
	manager.transitionLocked(StateRestarting)
	manager.status.OK = true
	manager.status.Error = nil
	manager.logInfo("detached rollback updater launched")
	return manager.status
}

func (manager *Manager) prepareArtifact(ctx context.Context, entry ManifestEntry) (string, uint64, error) {
	if err := ensureDirectory(manager.updateDirectory); err != nil {
		return "", 0, err
	}
	archivePath := filepath.Join(manager.updateDirectory, "ha4win-"+entry.Version+".zip")
	artifactBytes, err := manager.download(ctx, entry.AssetURL, archivePath)
	if err != nil {
		return "", 0, err
	}
	manager.mu.Lock()
	manager.transitionLocked(StateVerifying)
	manager.mu.Unlock()
	if err := verifySHA256(archivePath, entry.SHA256); err != nil {
		_ = os.Remove(archivePath)
		return "", artifactBytes, err
	}
	stagingDirectory := cleanStagingPath(manager.updateDirectory)
	if err := os.RemoveAll(stagingDirectory); err != nil {
		return "", artifactBytes, fmt.Errorf("clean staging directory: %w", err)
	}
	if err := ensureDirectory(stagingDirectory); err != nil {
		return "", artifactBytes, err
	}
	stagedPath := filepath.Join(stagingDirectory, "ha4win.exe")
	if err := extractExecutable(archivePath, stagedPath); err != nil {
		return "", artifactBytes, err
	}
	if manager.cfg.Management.RemoteUpdate.RequireSignedAsset {
		valid, err := manager.system.VerifyAuthenticode(stagedPath)
		if err != nil || !valid {
			if err == nil {
				err = fmt.Errorf("asset does not have a valid Authenticode signature")
			}
			return "", artifactBytes, err
		}
	}
	binaryArchitecture, err := manager.system.BinaryArchitecture(stagedPath)
	if err != nil {
		return "", artifactBytes, err
	}
	if binaryArchitecture != manager.architecture {
		return "", artifactBytes, fmt.Errorf("staged binary architecture %s does not match host architecture %s", binaryArchitecture, manager.architecture)
	}
	testContext, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	stagedVersion, err := manager.system.TestBinaryVersion(testContext, stagedPath)
	if err != nil {
		return "", artifactBytes, err
	}
	if stagedVersion != entry.Version {
		return "", artifactBytes, fmt.Errorf("staged binary version %q does not match manifest version %q", stagedVersion, entry.Version)
	}
	return stagedPath, artifactBytes, nil
}

func (manager *Manager) download(ctx context.Context, assetURL, destination string) (uint64, error) {
	timeout := time.Duration(manager.cfg.Management.RemoteUpdate.ApplyTimeoutSec) * time.Second
	downloadContext, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	request, err := http.NewRequestWithContext(downloadContext, http.MethodGet, assetURL, nil)
	if err != nil {
		return 0, err
	}
	response, err := manager.client.Do(request)
	if err != nil {
		return 0, fmt.Errorf("asset download failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("asset download returned HTTP %d", response.StatusCode)
	}
	if response.ContentLength > maxAssetSize {
		return 0, fmt.Errorf("update asset exceeds 64 MiB")
	}
	freeBefore, freeErr := manager.system.FreeSpace(manager.updateDirectory)
	if freeErr != nil {
		return 0, fmt.Errorf("query update directory free space: %w", freeErr)
	}
	if response.ContentLength > 0 && freeBefore < uint64(response.ContentLength)*3 {
		return 0, fmt.Errorf("update directory has %d bytes free; %d bytes are required", freeBefore, uint64(response.ContentLength)*3)
	}
	temporary := destination + ".part"
	file, err := os.OpenFile(temporary, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return 0, fmt.Errorf("create asset candidate: %w", err)
	}
	written, copyErr := io.Copy(file, io.LimitReader(response.Body, maxAssetSize+1))
	if copyErr == nil && written > maxAssetSize {
		copyErr = fmt.Errorf("update asset exceeds 64 MiB")
	}
	if copyErr == nil {
		copyErr = file.Sync()
	}
	closeErr := file.Close()
	if copyErr != nil {
		_ = os.Remove(temporary)
		return 0, fmt.Errorf("download update asset: %w", copyErr)
	}
	if closeErr != nil {
		_ = os.Remove(temporary)
		return 0, closeErr
	}
	if err := os.Rename(temporary, destination); err != nil {
		_ = os.Remove(temporary)
		return 0, fmt.Errorf("promote downloaded asset: %w", err)
	}
	if response.ContentLength <= 0 && freeBefore < uint64(written)*3 {
		_ = os.Remove(destination)
		return 0, fmt.Errorf("update directory had %d bytes free; %d bytes are required", freeBefore, uint64(written)*3)
	}
	return uint64(written), nil
}

func verifySHA256(path, expected string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return err
	}
	actual := hex.EncodeToString(hash.Sum(nil))
	if !strings.EqualFold(actual, strings.TrimSpace(expected)) {
		return fmt.Errorf("asset sha256 mismatch: expected %s, got %s", strings.ToLower(expected), actual)
	}
	return nil
}

func extractExecutable(archivePath, destination string) error {
	archive, err := zip.OpenReader(archivePath)
	if err != nil {
		return fmt.Errorf("open update ZIP: %w", err)
	}
	defer archive.Close()
	var selected *zip.File
	for _, entry := range archive.File {
		if strings.EqualFold(filepath.Base(filepath.FromSlash(entry.Name)), "ha4win.exe") && !entry.FileInfo().IsDir() {
			if selected != nil {
				return fmt.Errorf("update ZIP contains multiple ha4win.exe entries")
			}
			selected = entry
		}
	}
	if selected == nil {
		return fmt.Errorf("update ZIP does not contain ha4win.exe")
	}
	if selected.UncompressedSize64 > maxAssetSize || selected.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("update ZIP contains an invalid executable entry")
	}
	source, err := selected.Open()
	if err != nil {
		return err
	}
	defer source.Close()
	target, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o700)
	if err != nil {
		return err
	}
	written, copyErr := io.Copy(target, io.LimitReader(source, maxAssetSize+1))
	if copyErr == nil && written > maxAssetSize {
		copyErr = fmt.Errorf("extracted executable exceeds 64 MiB")
	}
	if copyErr == nil {
		copyErr = target.Sync()
	}
	closeErr := target.Close()
	if copyErr != nil {
		_ = os.Remove(destination)
		return copyErr
	}
	if closeErr != nil {
		_ = os.Remove(destination)
		return closeErr
	}
	return nil
}

func (manager *Manager) refreshPreflightLocked(artifactBytes uint64) {
	underSCM, _ := manager.system.RunningUnderSCM()
	freeBytes, _ := manager.system.FreeSpace(manager.updateDirectory)
	if artifactBytes > 0 {
		// The artifact is already present when this exact-size preflight runs.
		// Add it back to evaluate the free space that existed before download.
		freeBytes += artifactBytes
	}
	build, _ := manager.system.WindowsBuild()
	pendingReboot, _ := manager.system.PendingReboot()
	entry := ManifestEntry{}
	if manager.manifest != nil {
		entry = *manager.manifest
	}
	preflight := EvaluatePreflight(PreflightInput{
		RunningUnderSCM: underSCM, InstallWritable: manager.system.DirectoryWritable(filepath.Dir(manager.installPath)),
		FreeBytes: freeBytes, ArtifactBytes: artifactBytes, UpdateInProgress: manager.operationInProgressLocked(),
		AssetURL: entry.AssetURL, HostArchitecture: manager.architecture, AssetArchitecture: AssetArchitecture(entry.AssetURL),
		WindowsBuild: build, MinWindowsBuild: entry.MinWindowsBuild, ReadonlyMode: manager.cfg.ReadonlyMode,
		AllowInReadonly: manager.cfg.Management.RemoteUpdate.AllowInReadonly,
		RequireSigned:   manager.cfg.Management.RemoteUpdate.RequireSignedAsset, SignatureValid: false, PendingReboot: pendingReboot,
	})
	manager.status.Preflight = preflight
	manager.status.SupportsApplyReason = preflight.Reason
	manager.status.SupportsApply = manager.status.Enabled && manager.status.UpdateAvailable && preflight.CanApply
	manager.status.SupportsRollback = manager.status.Enabled && manager.status.RollbackVersion != nil && !manager.operationInProgressLocked()
}

func (manager *Manager) rollbackPreflightLocked() Preflight {
	underSCM, _ := manager.system.RunningUnderSCM()
	freeBytes, _ := manager.system.FreeSpace(filepath.Dir(manager.installPath))
	artifactBytes := uint64(0)
	if info, err := os.Stat(manager.previousPath); err == nil {
		artifactBytes = uint64(info.Size())
	}
	pendingReboot, _ := manager.system.PendingReboot()
	return EvaluatePreflight(PreflightInput{
		RunningUnderSCM: underSCM, InstallWritable: manager.system.DirectoryWritable(filepath.Dir(manager.installPath)),
		FreeBytes: freeBytes, ArtifactBytes: artifactBytes, UpdateInProgress: manager.operationInProgressLocked(),
		AssetURL: manager.previousPath, HostArchitecture: manager.architecture, AssetArchitecture: manager.architecture,
		ReadonlyMode: manager.cfg.ReadonlyMode, AllowInReadonly: manager.cfg.Management.RemoteUpdate.AllowInReadonly,
		PendingReboot: pendingReboot,
	})
}

func (manager *Manager) operationInProgressLocked() bool {
	_, err := os.Stat(manager.lockPath)
	return err == nil && !manager.ownedLock
}

func (manager *Manager) refreshRollbackVersion() {
	if _, err := os.Stat(manager.previousPath); err != nil {
		manager.status.RollbackVersion = nil
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	previousVersion, err := manager.system.TestBinaryVersion(ctx, manager.previousPath)
	if err != nil {
		manager.status.RollbackVersion = nil
		return
	}
	manager.status.RollbackVersion = stringPointer(previousVersion)
}

func (manager *Manager) loadPreviousOutcome() {
	manager.reconcilePersistentOutcomeLocked()
}

func (manager *Manager) reconcilePersistentOutcomeLocked() {
	state, err := ReadPersistentState(manager.statePath)
	if err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			manager.status.LastError = stringPointer(err.Error())
		}
		return
	}
	manager.status.TargetVersion = optionalString(state.TargetVersion)
	if state.Result != "" && state.CompletedAt != nil {
		manager.status.LastAppliedAt = state.CompletedAt
		manager.status.State = StateIdle
		if !manager.status.Enabled {
			manager.status.State = StateDisabled
		}
		manager.status.OK = true
		manager.status.Error = nil
		if state.Result != "success" {
			message := state.Error
			if message == "" {
				message = state.Result
			}
			manager.status.LastError = stringPointer(message)
			manager.persistentError = true
		} else {
			manager.status.LastError = nil
			manager.persistentError = false
		}
		_ = os.Remove(manager.lockPath)
		manager.ownedLock = false
		return
	}
	manager.status.State = state.State
	manager.status.OK = true
	manager.status.Error = nil
}

func (manager *Manager) transitionLocked(next string) {
	if manager.status.State == next {
		return
	}
	if CanTransition(manager.status.State, next) {
		manager.status.State = next
		return
	}
	manager.status.State = next
}

func (manager *Manager) failLocked(message, state string) Status {
	manager.transitionLocked(state)
	manager.status.OK = false
	manager.status.Error = stringPointer(message)
	manager.status.LastError = stringPointer(message)
	manager.status.SupportsApply = false
	manager.logError(message)
	return manager.status
}

func randomOperationID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("create update operation ID: %w", err)
	}
	return hex.EncodeToString(buffer), nil
}

func stringPointer(value string) *string { return &value }
func optionalString(value string) *string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return stringPointer(value)
}

func (manager *Manager) logInfo(message string) {
	if manager.logger != nil {
		manager.logger.Info(message)
	}
}

func (manager *Manager) logError(message string) {
	if manager.logger != nil {
		manager.logger.Error(message)
	}
}
