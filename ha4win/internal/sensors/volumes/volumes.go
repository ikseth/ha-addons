package volumes

import (
	"context"
	"math"
	"sort"
	"strings"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type Source interface {
	LogicalDrives() ([]winapi.LogicalDrive, error)
	Volume(string) (winapi.VolumeInformation, error)
}

type systemSource struct{}

func (systemSource) LogicalDrives() ([]winapi.LogicalDrive, error) { return winapi.GetLogicalDrives() }
func (systemSource) Volume(root string) (winapi.VolumeInformation, error) {
	return winapi.GetVolume(root)
}

type Sensor struct {
	source       Source
	driveTypes   map[string]bool
	excludeMount map[string]bool
}

func New(includeDriveTypes, excludeMounts []string, source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	return &Sensor{
		source: source, driveTypes: normalizeSet(includeDriveTypes, strings.ToLower),
		excludeMount: normalizeSet(excludeMounts, mountKey),
	}
}

func (*Sensor) ID() string { return "volumes" }

func (s *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	drives, err := s.source.LogicalDrives()
	if err != nil {
		return nil, err
	}
	items := make([]map[string]any, 0, len(drives))
	for _, drive := range drives {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		mountpoint := normalizeMountpoint(drive.Root)
		if !s.driveTypes[strings.ToLower(drive.Type)] || s.excludeMount[mountKey(mountpoint)] {
			continue
		}
		information, err := s.source.Volume(drive.Root)
		if err != nil {
			return nil, err
		}
		if information.TotalBytes == 0 {
			continue
		}
		free := min(information.FreeBytes, information.TotalBytes)
		used := information.TotalBytes - free
		items = append(items, map[string]any{
			"mountpoint": mountpoint, "label": information.Label, "fs_type": information.FileSystem,
			"drive_type": strings.ToLower(drive.Type), "readonly": information.ReadOnly,
			"total_bytes": information.TotalBytes, "used_bytes": used, "free_bytes": free,
			"total_gib": gib(information.TotalBytes), "used_gib": gib(used), "free_gib": gib(free),
			"used_percent": percent(used, information.TotalBytes),
		})
	}
	sort.Slice(items, func(left, right int) bool {
		return items[left]["mountpoint"].(string) < items[right]["mountpoint"].(string)
	})
	readOnly := 0
	over90 := 0
	for _, item := range items {
		if item["readonly"].(bool) {
			readOnly++
		}
		if item["used_percent"].(float64) >= 90 {
			over90++
		}
	}
	return map[string]any{
		"volumes_total": len(items), "volumes_readonly": readOnly, "volumes_over_90": over90, "volumes": items,
	}, nil
}

func normalizeSet(values []string, normalize func(string) string) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		if value = normalize(strings.TrimSpace(value)); value != "" {
			result[value] = true
		}
	}
	return result
}

func normalizeMountpoint(value string) string {
	value = strings.TrimSpace(value)
	if len(value) == 3 && value[1] == ':' && (value[2] == '\\' || value[2] == '/') {
		value = value[:2]
	}
	if len(value) >= 2 && value[1] == ':' {
		value = strings.ToUpper(value[:1]) + value[1:]
	}
	return value
}

func mountKey(value string) string { return strings.ToLower(normalizeMountpoint(value)) }

func gib(value uint64) float64 { return math.Round(float64(value)/(1024*1024*1024)*100) / 100 }

func percent(value, total uint64) float64 {
	if total == 0 {
		return 0
	}
	return math.Round(float64(value)*10000/float64(total)) / 100
}
