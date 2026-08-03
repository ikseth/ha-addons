package cpu

import (
	"context"
	"runtime"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type Source interface {
	SystemTimes() (winapi.CPUTimes, error)
	ProcessorTimes() ([]winapi.CPUTimes, error)
	Performance() (winapi.CPUPerformance, error)
}

type systemSource struct{}

func (systemSource) SystemTimes() (winapi.CPUTimes, error) { return winapi.GetSystemTimes() }
func (systemSource) ProcessorTimes() ([]winapi.CPUTimes, error) {
	return winapi.GetProcessorPerformance()
}
func (systemSource) Performance() (winapi.CPUPerformance, error) {
	return winapi.GetSystemPerformance()
}

type percentages struct {
	usage  float64
	user   float64
	kernel float64
}

type Sensor struct {
	mu            sync.Mutex
	source        Source
	perCore       bool
	now           func() time.Time
	previous      *winapi.CPUTimes
	previousCores []winapi.CPUTimes
	previousAt    time.Time
	last          percentages
	lastCore      []float64
	lastWindow    float64
}

func New(perCore bool, source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	sensor := &Sensor{source: source, perCore: perCore, now: time.Now}
	sensor.initialize()
	return sensor
}

func (s *Sensor) ID() string { return "cpu" }

func (s *Sensor) initialize() {
	now := s.now()
	if sample, err := s.source.SystemTimes(); err == nil {
		s.previous = &sample
		s.previousAt = now
	}
	if s.perCore {
		if samples, err := s.source.ProcessorTimes(); err == nil {
			s.previousCores = samples
			s.lastCore = make([]float64, len(samples))
		}
	}
}

func (s *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now()
	current, err := s.source.SystemTimes()
	if err != nil {
		return nil, err
	}
	performance, err := s.source.Performance()
	if err != nil {
		return nil, err
	}
	logicalProcessors := runtime.NumCPU()
	var coreSamples []winapi.CPUTimes
	coreAvailable := false
	if s.perCore {
		if samples, coreErr := s.source.ProcessorTimes(); coreErr == nil {
			coreSamples = samples
			coreAvailable = true
			if len(samples) > 0 {
				logicalProcessors = len(samples)
			}
		}
	}

	if s.previous == nil {
		s.previous = &current
		s.previousAt = now
		if len(coreSamples) > 0 {
			s.previousCores = coreSamples
			s.lastCore = make([]float64, len(coreSamples))
		}
	} else if elapsed := now.Sub(s.previousAt); elapsed >= time.Second {
		s.last = calculatePercentages(*s.previous, current)
		s.lastWindow = elapsed.Seconds()
		if len(coreSamples) > 0 {
			s.lastCore = calculateCorePercentages(s.previousCores, coreSamples)
			s.previousCores = coreSamples
		}
		s.previous = &current
		s.previousAt = now
	}

	data := map[string]any{
		"usage_percent": round(s.last.usage, 2), "usage_user_percent": round(s.last.user, 2),
		"usage_kernel_percent": round(s.last.kernel, 2), "logical_processors": logicalProcessors,
		"processes": performance.Processes, "threads": performance.Threads, "handles": performance.Handles,
		"window_seconds": round(s.lastWindow, 3),
	}
	if s.perCore && coreAvailable && len(s.lastCore) > 0 {
		cores := make([]map[string]any, len(s.lastCore))
		for index, usage := range s.lastCore {
			cores[index] = map[string]any{"index": index, "usage_percent": round(usage, 2)}
		}
		data["per_core"] = cores
	}
	return data, nil
}

func calculatePercentages(previous, current winapi.CPUTimes) percentages {
	idle := counterDelta(previous.Idle, current.Idle)
	kernel := counterDelta(previous.Kernel, current.Kernel)
	user := counterDelta(previous.User, current.User)
	total := kernel + user
	if total == 0 {
		return percentages{}
	}
	activeKernel := uint64(0)
	if kernel > idle {
		activeKernel = kernel - idle
	}
	return percentages{
		usage: float64(user+activeKernel) * 100 / float64(total),
		user:  float64(user) * 100 / float64(total), kernel: float64(activeKernel) * 100 / float64(total),
	}
}

func calculateCorePercentages(previous, current []winapi.CPUTimes) []float64 {
	result := make([]float64, len(current))
	for index := range current {
		if index < len(previous) {
			result[index] = calculatePercentages(previous[index], current[index]).usage
		}
	}
	return result
}

func counterDelta(previous, current uint64) uint64 {
	if current >= previous {
		return current - previous
	}
	return current
}

func round(value float64, precision int) float64 {
	multiplier := 1.0
	for range precision {
		multiplier *= 10
	}
	return float64(int64(value*multiplier+0.5)) / multiplier
}
