package services

import (
	"context"
	"sort"
	"strings"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

const errorServiceNeverStarted = 1077

type Source interface {
	Service(string) (winapi.WatchedService, error)
}

type systemSource struct{}

func (systemSource) Service(name string) (winapi.WatchedService, error) {
	return winapi.QueryService(name)
}

type Sensor struct {
	watchlist []string
	source    Source
}

func New(watchlist []string, source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	return &Sensor{watchlist: NormalizeWatchlist(watchlist), source: source}
}

func (*Sensor) ID() string { return "services" }

func (s *Sensor) Available() (bool, string) {
	if len(s.watchlist) == 0 {
		return false, "services watchlist is empty"
	}
	return true, ""
}

func (s *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	items := make([]map[string]any, 0, len(s.watchlist))
	seenServices := make(map[string]bool, len(s.watchlist))
	for _, requested := range s.watchlist {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		service, err := s.source.Service(requested)
		if err != nil {
			return nil, err
		}
		if !service.Exists {
			continue
		}
		serviceKey := strings.ToLower(service.Name)
		if seenServices[serviceKey] {
			continue
		}
		seenServices[serviceKey] = true
		active := service.Status == "running"
		failed := service.Status == "stopped" && (service.StartType == "auto" || service.StartType == "auto_delayed") && service.ExitCode != 0 && service.ExitCode != errorServiceNeverStarted
		items = append(items, map[string]any{
			"name": service.Name, "display_name": service.DisplayName, "exists": true,
			"status": service.Status, "start_type": service.StartType, "pid": service.PID,
			"is_active": active, "is_failed": failed, "can_stop": service.CanStop, "exit_code": service.ExitCode,
		})
	}
	sort.Slice(items, func(left, right int) bool {
		return strings.ToLower(items[left]["name"].(string)) < strings.ToLower(items[right]["name"].(string))
	})
	active := 0
	failed := 0
	for _, item := range items {
		if item["is_active"].(bool) {
			active++
		}
		if item["is_failed"].(bool) {
			failed++
		}
	}
	return map[string]any{
		"services_total": len(items), "services_active": active, "services_failed": failed, "services": items,
	}, nil
}

func NormalizeWatchlist(watchlist []string) []string {
	result := make([]string, 0, len(watchlist))
	seen := make(map[string]bool, len(watchlist))
	for _, raw := range watchlist {
		name := strings.TrimSpace(raw)
		key := strings.ToLower(name)
		if name == "" || seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, name)
	}
	return result
}
