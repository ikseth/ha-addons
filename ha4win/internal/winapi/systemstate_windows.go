//go:build windows

package winapi

import (
	"errors"
	"fmt"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

var procGetSystemPowerStatus = kernel32.NewProc("GetSystemPowerStatus")

type windowsRegistryReader struct{}

func newRegistryReader() RegistryReader { return windowsRegistryReader{} }

func openTelemetryKey(path string) (registry.Key, error) {
	return registry.OpenKey(registry.LOCAL_MACHINE, path, registry.QUERY_VALUE|registry.WOW64_64KEY)
}

func (windowsRegistryReader) KeyExists(path string) (bool, error) {
	key, err := openTelemetryKey(path)
	if errors.Is(err, windows.ERROR_FILE_NOT_FOUND) || errors.Is(err, windows.ERROR_PATH_NOT_FOUND) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("open registry key %q: %w", path, err)
	}
	key.Close()
	return true, nil
}

func (windowsRegistryReader) String(path, name string) (string, error) {
	key, err := openTelemetryKey(path)
	if err != nil {
		return "", fmt.Errorf("open registry key %q: %w", path, err)
	}
	defer key.Close()
	value, _, err := key.GetStringValue(name)
	if err != nil {
		return "", fmt.Errorf("read registry value %q\\%s: %w", path, name, err)
	}
	return value, nil
}

func (windowsRegistryReader) Strings(path, name string) ([]string, error) {
	key, err := openTelemetryKey(path)
	if err != nil {
		return nil, fmt.Errorf("open registry key %q: %w", path, err)
	}
	defer key.Close()
	value, _, err := key.GetStringsValue(name)
	if errors.Is(err, windows.ERROR_FILE_NOT_FOUND) {
		return []string{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read registry value %q\\%s: %w", path, name, err)
	}
	return value, nil
}

func (windowsRegistryReader) DWORD(path, name string) (uint32, error) {
	key, err := openTelemetryKey(path)
	if err != nil {
		return 0, fmt.Errorf("open registry key %q: %w", path, err)
	}
	defer key.Close()
	value, _, err := key.GetIntegerValue(name)
	if err != nil {
		return 0, fmt.Errorf("read registry value %q\\%s: %w", path, name, err)
	}
	return uint32(value), nil
}

type systemPowerStatus struct {
	ACLineStatus        byte
	BatteryFlag         byte
	BatteryLifePercent  byte
	SystemStatusFlag    byte
	BatteryLifeTime     uint32
	BatteryFullLifeTime uint32
}

func getPowerStatus() (PowerStatus, error) {
	var status systemPowerStatus
	result, _, callErr := procGetSystemPowerStatus.Call(uintptr(unsafe.Pointer(&status)))
	if result == 0 {
		return PowerStatus{}, fmt.Errorf("GetSystemPowerStatus failed: %w", callErr)
	}
	return PowerStatus{ACLineStatus: status.ACLineStatus, BatteryFlag: status.BatteryFlag, BatteryLifePercent: status.BatteryLifePercent}, nil
}

func getUptime() (time.Duration, error) { return windows.DurationSinceBoot(), nil }

// Windows has no query API for the InitiateSystemShutdown countdown. Phase 3
// will replace this neutral source with the actuator's synchronized runtime state.
func shutdownPending() (bool, *string, error) { return false, nil, nil }
