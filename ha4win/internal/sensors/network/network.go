package network

import (
	"context"
	"math"
	"path"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type Source interface {
	Interfaces() ([]winapi.NetworkInterface, error)
}

type systemSource struct{}

func (systemSource) Interfaces() ([]winapi.NetworkInterface, error) {
	return winapi.GetNetworkInterfaces()
}

type counters struct {
	rx uint64
	tx uint64
}

type Sensor struct {
	mu             sync.Mutex
	source         Source
	include        []string
	exclude        []string
	aggregateMode  string
	now            func() time.Time
	lastInterfaces map[string]counters
	lastAggregate  *counters
	lastSample     time.Time
}

func New(include, exclude []string, aggregateMode string, source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	if aggregateMode != "all" {
		aggregateMode = "selected"
	}
	return &Sensor{
		source: source, include: cleanPatterns(include), exclude: cleanPatterns(exclude), aggregateMode: aggregateMode,
		now: time.Now, lastInterfaces: make(map[string]counters),
	}
}

func (*Sensor) ID() string { return "network" }

func (s *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	discovered, err := s.source.Interfaces()
	if err != nil {
		return nil, err
	}
	hardware := onlyHardware(discovered)
	available := filterInterfaces(hardware, nil, s.exclude)
	selected := filterInterfaces(available, s.include, nil)
	if len(s.include) == 0 {
		selected = onlyUp(selected)
	}
	aggregated := onlyUp(selected)
	if s.aggregateMode == "all" {
		aggregated = onlyUp(available)
	}

	total := counters{}
	for _, item := range aggregated {
		total.rx += item.RXBytes
		total.tx += item.TXBytes
	}
	now := s.now()
	delta := counters{}
	window := 0.0
	if s.lastAggregate != nil && !s.lastSample.IsZero() {
		delta.rx = counterDelta(s.lastAggregate.rx, total.rx)
		delta.tx = counterDelta(s.lastAggregate.tx, total.tx)
		window = max(now.Sub(s.lastSample).Seconds(), 0)
	}

	interfaceData := make(map[string]any, len(selected))
	selectedNames := make([]string, 0, len(selected))
	currentInterfaces := make(map[string]counters, len(selected))
	for _, item := range selected {
		selectedNames = append(selectedNames, item.Alias)
		current := counters{rx: item.RXBytes, tx: item.TXBytes}
		currentInterfaces[item.Alias] = current
		interfaceDelta := counters{}
		if previous, ok := s.lastInterfaces[item.Alias]; ok && !s.lastSample.IsZero() {
			interfaceDelta.rx = counterDelta(previous.rx, current.rx)
			interfaceDelta.tx = counterDelta(previous.tx, current.tx)
		}
		interfaceData[item.Alias] = map[string]any{
			"rx_bytes": item.RXBytes, "tx_bytes": item.TXBytes,
			"rx_kib_window": kib(interfaceDelta.rx), "tx_kib_window": kib(interfaceDelta.tx),
			"description": item.Description, "mac": item.MAC, "oper_status": item.OperStatus,
			"speed_mbps": item.SpeedMbps, "type": item.Type,
		}
	}
	sort.Strings(selectedNames)
	s.lastAggregate = &total
	s.lastInterfaces = currentInterfaces
	s.lastSample = now
	return map[string]any{
		"total_rx_bytes": total.rx, "total_tx_bytes": total.tx,
		"rx_kib_window": kib(delta.rx), "tx_kib_window": kib(delta.tx), "window_seconds": math.Round(window*1000) / 1000,
		"aggregate_mode": s.aggregateMode, "selected_interfaces": selectedNames, "interfaces": interfaceData,
	}, nil
}

func cleanPatterns(values []string) []string {
	result := make([]string, 0, len(values))
	for _, value := range values {
		if value = strings.TrimSpace(value); value != "" {
			result = append(result, value)
		}
	}
	return result
}

func onlyHardware(interfaces []winapi.NetworkInterface) []winapi.NetworkInterface {
	result := make([]winapi.NetworkInterface, 0, len(interfaces))
	for _, item := range interfaces {
		if item.Hardware {
			result = append(result, item)
		}
	}
	return result
}

func filterInterfaces(interfaces []winapi.NetworkInterface, include, exclude []string) []winapi.NetworkInterface {
	result := make([]winapi.NetworkInterface, 0, len(interfaces))
	for _, item := range interfaces {
		if item.Alias == "" || item.Loopback || item.Tunnel || matches(item.Alias, exclude) {
			continue
		}
		if len(include) > 0 && !matches(item.Alias, include) {
			continue
		}
		result = append(result, item)
	}
	return result
}

func matches(value string, patterns []string) bool {
	for _, pattern := range patterns {
		matched, err := path.Match(pattern, value)
		if err == nil && matched {
			return true
		}
	}
	return false
}

func onlyUp(interfaces []winapi.NetworkInterface) []winapi.NetworkInterface {
	result := make([]winapi.NetworkInterface, 0, len(interfaces))
	for _, item := range interfaces {
		if item.OperStatus == "up" {
			result = append(result, item)
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

func kib(value uint64) float64 { return math.Round(float64(value)/1024*100) / 100 }
