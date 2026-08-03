package maintenance

import (
	"context"
	"fmt"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

const (
	componentServicingKey = `SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending`
	windowsUpdateKey      = `SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired`
	sessionManagerKey     = `SYSTEM\CurrentControlSet\Control\Session Manager`
	computerNameKey       = `SYSTEM\CurrentControlSet\Control\ComputerName\ComputerName`
	activeComputerNameKey = `SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName`
	sccmKey               = `SOFTWARE\Microsoft\SMS\Mobile Client\Software Distribution\Execution Request State`
)

type Source interface {
	Registry() winapi.RegistryReader
	PowerStatus() (winapi.PowerStatus, error)
	Uptime() (time.Duration, error)
	ShutdownStatus() (bool, *string, error)
}

type systemSource struct{}

func (systemSource) Registry() winapi.RegistryReader          { return winapi.NewRegistryReader() }
func (systemSource) PowerStatus() (winapi.PowerStatus, error) { return winapi.GetPowerStatus() }
func (systemSource) Uptime() (time.Duration, error)           { return winapi.GetUptime() }
func (systemSource) ShutdownStatus() (bool, *string, error)   { return winapi.ShutdownPending() }

type Sensor struct {
	source Source
	now    func() time.Time
}

func New(source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	return &Sensor{source: source, now: time.Now}
}

func (*Sensor) ID() string { return "maintenance" }

func (sensor *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	reasons, err := PendingRebootReasons(sensor.source.Registry())
	if err != nil {
		return nil, err
	}
	uptime, err := sensor.source.Uptime()
	if err != nil {
		return nil, err
	}
	power, err := sensor.source.PowerStatus()
	if err != nil {
		return nil, err
	}
	shutdown, lastReason, err := sensor.source.ShutdownStatus()
	if err != nil {
		return nil, err
	}
	uptimeSeconds := max(int64(uptime/time.Second), 0)
	bootTime := sensor.now().UTC().Add(-time.Duration(uptimeSeconds) * time.Second)
	batteryPresent := power.BatteryFlag != 255 && power.BatteryFlag&128 == 0
	batteryPercent := int(power.BatteryLifePercent)
	if !batteryPresent || power.BatteryLifePercent == 255 {
		batteryPercent = 0
	}
	var lastShutdownReason any
	if lastReason != nil {
		lastShutdownReason = *lastReason
	}
	return map[string]any{
		"pending_reboot":         len(reasons) > 0,
		"pending_reboot_reasons": reasons,
		"boot_time":              bootTime.Format(time.RFC3339),
		"uptime_seconds":         uptimeSeconds,
		"power_source":           powerSource(power.ACLineStatus),
		"battery_present":        batteryPresent,
		"battery_percent":        batteryPercent,
		"battery_charging":       batteryPresent && power.BatteryFlag&8 != 0,
		"shutdown_pending":       shutdown,
		"last_shutdown_reason":   lastShutdownReason,
	}, nil
}

func PendingRebootReasons(reader winapi.RegistryReader) ([]string, error) {
	reasons := make([]string, 0, 5)
	for _, candidate := range []struct{ reason, path string }{
		{"component_based_servicing", componentServicingKey},
		{"windows_update", windowsUpdateKey},
	} {
		exists, err := reader.KeyExists(candidate.path)
		if err != nil {
			return nil, fmt.Errorf("check %s reboot marker: %w", candidate.reason, err)
		}
		if exists {
			reasons = append(reasons, candidate.reason)
		}
	}
	renames, err := reader.Strings(sessionManagerKey, "PendingFileRenameOperations")
	if err != nil {
		return nil, fmt.Errorf("check pending file rename marker: %w", err)
	}
	if len(renames) > 0 {
		reasons = append(reasons, "pending_file_rename")
	}
	configuredName, err := reader.String(computerNameKey, "ComputerName")
	if err != nil {
		return nil, fmt.Errorf("read configured computer name: %w", err)
	}
	activeName, err := reader.String(activeComputerNameKey, "ComputerName")
	if err != nil {
		return nil, fmt.Errorf("read active computer name: %w", err)
	}
	if configuredName != activeName {
		reasons = append(reasons, "computer_rename")
	}
	sccm, err := reader.KeyExists(sccmKey)
	if err != nil {
		return nil, fmt.Errorf("check SCCM reboot marker: %w", err)
	}
	if sccm {
		reasons = append(reasons, "sccm")
	}
	return reasons, nil
}

func powerSource(value byte) string {
	switch value {
	case 0:
		return "battery"
	case 1:
		return "ac"
	default:
		return "unknown"
	}
}
