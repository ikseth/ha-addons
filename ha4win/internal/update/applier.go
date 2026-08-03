package update

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type ApplyPlatform interface {
	StopService(time.Duration) error
	StartService() error
	ReplaceFile(source, destination string) error
}

type ApplierOptions struct {
	Platform ApplyPlatform
	Now      func() time.Time
}

type Applier struct {
	platform ApplyPlatform
	now      func() time.Time
}

func NewApplier(options ApplierOptions) *Applier {
	if options.Platform == nil {
		options.Platform = winapi.Current()
	}
	if options.Now == nil {
		options.Now = time.Now
	}
	return &Applier{platform: options.Platform, now: options.Now}
}

func (applier *Applier) Run(statePath string) error {
	state, err := ReadPersistentState(statePath)
	if err != nil {
		return err
	}
	lockPath := filepath.Join(filepath.Dir(statePath), "update.lock")
	defer os.Remove(lockPath)
	if err := claimFileLock(lockPath, state.OperationID); err != nil {
		return applier.finish(statePath, &state, "error", err)
	}
	if err := validateApplyState(state); err != nil {
		return applier.finish(statePath, &state, "error", err)
	}
	waitBeforeServiceStop()
	newPath := state.InstallPath + ".new"
	_ = os.Remove(newPath)
	if err := copyAndFlush(state.StagedPath, newPath); err != nil {
		return applier.finish(statePath, &state, "error", fmt.Errorf("prepare .new executable: %w", err))
	}
	if err := applier.platform.StopService(60 * time.Second); err != nil {
		_ = os.Remove(newPath)
		return applier.finish(statePath, &state, "error", fmt.Errorf("stop service before swap: %w", err))
	}
	state.State = StateApplying
	if state.Operation == "rollback" {
		state.State = StateRollback
	}
	if err := WritePersistentState(statePath, state); err != nil {
		startErr := applier.platform.StartService()
		return applier.finish(statePath, &state, "error", fmt.Errorf("persist pre-swap state: %w; service start error: %v", err, startErr))
	}
	if err := applier.platform.ReplaceFile(state.InstallPath, state.PreviousPath); err != nil {
		_ = os.Remove(newPath)
		_ = applier.platform.StartService()
		return applier.finish(statePath, &state, "error", fmt.Errorf("preserve current executable as .previous: %w", err))
	}
	if err := applier.platform.ReplaceFile(newPath, state.InstallPath); err != nil {
		restoreErr := applier.platform.ReplaceFile(state.PreviousPath, state.InstallPath)
		startErr := applier.platform.StartService()
		failure := fmt.Errorf("promote .new executable: %w", err)
		if restoreErr != nil || startErr != nil {
			failure = fmt.Errorf("%w; immediate restore error: %v; service start error: %v", failure, restoreErr, startErr)
		}
		return applier.finish(statePath, &state, "rolled_back", failure)
	}
	state.State = StateRestarting
	if err := WritePersistentState(statePath, state); err != nil {
		return applier.rollbackAfterPromotion(statePath, &state, err)
	}
	if err := applier.platform.StartService(); err != nil {
		return applier.rollbackAfterPromotion(statePath, &state, fmt.Errorf("start updated service: %w", err))
	}
	loaded, err := config.Load(state.ConfigPath, os.LookupEnv)
	if err != nil {
		return applier.rollbackAfterPromotion(statePath, &state, fmt.Errorf("load configuration for health-check: %w", err))
	}
	healthTimeout := time.Duration(loaded.Config.Management.RemoteUpdate.HealthCheckTimeoutSec) * time.Second
	if err := HealthCheck(loaded.Config, healthTimeout); err != nil {
		return applier.rollbackAfterPromotion(statePath, &state, err)
	}
	_ = os.Remove(newPath)
	if state.Operation == "apply" {
		_ = os.RemoveAll(filepath.Dir(state.StagedPath))
	}
	return applier.finish(statePath, &state, "success", nil)
}

func validateApplyState(state PersistentState) error {
	if state.Operation != "apply" && state.Operation != "rollback" {
		return fmt.Errorf("unsupported update operation %q", state.Operation)
	}
	for name, path := range map[string]string{
		"staged_path": state.StagedPath, "install_path": state.InstallPath, "previous_path": state.PreviousPath, "config_path": state.ConfigPath,
	} {
		if strings.TrimSpace(path) == "" || !filepath.IsAbs(path) {
			return fmt.Errorf("%s must be an absolute path", name)
		}
	}
	if !strings.EqualFold(filepath.Base(state.InstallPath), "ha4win.exe") || state.PreviousPath != state.InstallPath+".previous" {
		return fmt.Errorf("update state contains an invalid installation target")
	}
	if info, err := os.Stat(state.StagedPath); err != nil || info.IsDir() {
		return fmt.Errorf("staged executable is unavailable")
	}
	return nil
}

func copyAndFlush(sourcePath, destinationPath string) error {
	source, err := os.Open(sourcePath)
	if err != nil {
		return err
	}
	defer source.Close()
	destination, err := os.OpenFile(destinationPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o700)
	if err != nil {
		return err
	}
	removeDestination := true
	defer func() {
		_ = destination.Close()
		if removeDestination {
			_ = os.Remove(destinationPath)
		}
	}()
	if _, err := io.Copy(destination, source); err != nil {
		return err
	}
	if err := destination.Sync(); err != nil {
		return err
	}
	if err := destination.Close(); err != nil {
		return err
	}
	removeDestination = false
	return nil
}

func (applier *Applier) rollbackAfterPromotion(statePath string, state *PersistentState, cause error) error {
	state.State = StateRollback
	_ = WritePersistentState(statePath, *state)
	stopErr := applier.platform.StopService(60 * time.Second)
	restoreErr := applier.platform.ReplaceFile(state.PreviousPath, state.InstallPath)
	startErr := applier.platform.StartService()
	resultErr := cause
	if stopErr != nil || restoreErr != nil || startErr != nil {
		resultErr = fmt.Errorf("%w; rollback stop error: %v; restore error: %v; restart error: %v", cause, stopErr, restoreErr, startErr)
	} else {
		loaded, loadErr := config.Load(state.ConfigPath, os.LookupEnv)
		if loadErr != nil {
			resultErr = fmt.Errorf("%w; load configuration after rollback: %v", cause, loadErr)
		} else if healthErr := HealthCheck(loaded.Config, time.Duration(loaded.Config.Management.RemoteUpdate.HealthCheckTimeoutSec)*time.Second); healthErr != nil {
			resultErr = fmt.Errorf("%w; restored service health-check failed: %v", cause, healthErr)
		}
	}
	return applier.finish(statePath, state, "rolled_back", resultErr)
}

func (applier *Applier) finish(statePath string, state *PersistentState, result string, resultErr error) error {
	completed := applier.now().UTC()
	state.CompletedAt = &completed
	state.Result = result
	state.State = StateIdle
	if resultErr != nil {
		state.Error = resultErr.Error()
	}
	if err := WritePersistentState(statePath, *state); err != nil {
		return fmt.Errorf("persist update result: %w", err)
	}
	return resultErr
}

func HealthCheck(cfg config.Config, timeout time.Duration) error {
	host := strings.TrimSpace(cfg.API.BindHost)
	if host == "0.0.0.0" {
		host = "127.0.0.1"
	} else if host == "::" || host == "[::]" {
		host = "::1"
	}
	scheme := "http"
	transport := &http.Transport{}
	if cfg.TLS.Enabled {
		scheme = "https"
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} // The updater probes the configured local self-signed endpoint.
	}
	endpoint := scheme + "://" + net.JoinHostPort(host, strconv.Itoa(cfg.API.BindPort)) + "/health"
	deadline := time.Now().Add(timeout)
	var lastErr error
	for time.Now().Before(deadline) {
		attemptTimeout := 2 * time.Second
		if remaining := time.Until(deadline); remaining < attemptTimeout {
			attemptTimeout = remaining
		}
		ctx, cancel := context.WithTimeout(context.Background(), attemptTimeout)
		request, _ := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		response, err := (&http.Client{Transport: transport, Timeout: attemptTimeout}).Do(request)
		if err == nil {
			var payload struct {
				Status string `json:"status"`
			}
			decodeErr := json.NewDecoder(io.LimitReader(response.Body, 4096)).Decode(&payload)
			_ = response.Body.Close()
			if response.StatusCode == http.StatusOK && decodeErr == nil && payload.Status == "ok" {
				cancel()
				return nil
			}
			lastErr = fmt.Errorf("HTTP %d with an invalid health payload", response.StatusCode)
		} else {
			lastErr = err
		}
		cancel()
		if time.Until(deadline) > 250*time.Millisecond {
			time.Sleep(250 * time.Millisecond)
		}
	}
	return fmt.Errorf("health-check %s failed within %s: %v", endpoint, timeout, lastErr)
}
