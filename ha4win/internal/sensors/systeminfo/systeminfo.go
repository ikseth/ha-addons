package systeminfo

import (
	"context"
	"fmt"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type Source interface {
	WindowsInformation() (winapi.WindowsInformation, error)
}

type systemSource struct{}

func (systemSource) WindowsInformation() (winapi.WindowsInformation, error) {
	return winapi.GetWindowsInformation()
}

type Sensor struct {
	source  Source
	now     func() time.Time
	updates *updatesCache
}

func New(source Source) *Sensor {
	return NewWithUpdates(source, UpdatesOptions{Enabled: false, Provider: "disabled", CheckInterval: 24 * time.Hour, Timeout: 10 * time.Minute, MaxPackages: 25})
}

func NewWithUpdates(source Source, options UpdatesOptions) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	return &Sensor{source: source, now: time.Now, updates: newUpdatesCache(options)}
}

func (*Sensor) ID() string { return "system_info" }

func (s *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	info, err := s.source.WindowsInformation()
	if err != nil {
		return nil, err
	}
	productName := info.ProductName
	if info.BuildNumber >= 22000 {
		productName = strings.Replace(productName, "Windows 10", "Windows 11", 1)
	}
	if strings.TrimSpace(productName) == "" {
		productName = info.EditionID
	}
	build := info.CurrentBuild
	if build == "" {
		build = strconv.FormatUint(uint64(info.BuildNumber), 10)
	}
	build = fmt.Sprintf("%s.%d", build, info.UBR)
	uptimeSeconds := max(int64(info.Uptime/time.Second), 0)
	bootTime := s.now().UTC().Add(-time.Duration(uptimeSeconds) * time.Second)
	data := map[string]any{
		"hostname": info.Hostname, "os_name": "Windows", "edition": productName,
		"display_version": info.DisplayVersion, "build": build,
		"major": info.Major, "minor": info.Minor, "build_number": info.BuildNumber, "ubr": info.UBR,
		"architecture": runtime.GOARCH, "install_date": info.InstallDate.UTC().Format(time.RFC3339),
		"boot_time": bootTime.Format(time.RFC3339), "uptime_seconds": uptimeSeconds,
		"domain": info.Domain, "domain_joined": info.DomainJoined,
	}
	for key, value := range s.updates.data() {
		data[key] = value
	}
	return data, nil
}
