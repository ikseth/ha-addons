package memory

import (
	"context"
	"math"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type Source interface {
	MemoryStatus() (winapi.MemoryStatus, error)
}

type systemSource struct{}

func (systemSource) MemoryStatus() (winapi.MemoryStatus, error) { return winapi.GetMemoryStatus() }

type Sensor struct{ source Source }

func New(source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	return &Sensor{source: source}
}

func (*Sensor) ID() string { return "memory" }

func (s *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	status, err := s.source.MemoryStatus()
	if err != nil {
		return nil, err
	}
	used := uint64(0)
	if status.TotalPhysical > status.AvailablePhysical {
		used = status.TotalPhysical - status.AvailablePhysical
	}
	return map[string]any{
		"total_kb": status.TotalPhysical / 1024, "available_kb": status.AvailablePhysical / 1024, "used_kb": used / 1024,
		"used_percent": percentage(used, status.TotalPhysical), "commit_total_kb": status.CommitTotal / 1024,
		"commit_limit_kb": status.CommitLimit / 1024, "commit_percent": percentage(status.CommitTotal, status.CommitLimit),
	}, nil
}

func percentage(value, total uint64) float64 {
	if total == 0 {
		return 0
	}
	return math.Round(float64(value)*10000/float64(total)) / 100
}
