package systeminfo

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strings"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
	wincom "github.com/ikseth/ha-addons/ha4win/internal/winapi/com"
)

type UpdatesOptions struct {
	Enabled       bool
	Provider      string
	SearchScope   string
	CheckInterval time.Duration
	Timeout       time.Duration
	MaxPackages   int
	ProviderImpl  updatesProvider
}

type updatesProvider interface {
	Name() string
	Check(context.Context, string) (wincom.UpdateSnapshot, error)
}

type unsupportedUpdatesError struct{ reason string }

func (err unsupportedUpdatesError) Error() string { return err.reason }

type wuaProvider struct{}

func (wuaProvider) Name() string { return "wua" }
func (wuaProvider) Check(ctx context.Context, scope string) (wincom.UpdateSnapshot, error) {
	service, err := winapi.QueryService("wuauserv")
	if err != nil {
		return wincom.UpdateSnapshot{}, fmt.Errorf("query wuauserv: %w", err)
	}
	if !service.Exists {
		return wincom.UpdateSnapshot{}, unsupportedUpdatesError{reason: "Windows Update service (wuauserv) is not installed"}
	}
	if service.StartType == "disabled" {
		return wincom.UpdateSnapshot{}, unsupportedUpdatesError{reason: "Windows Update service (wuauserv) is disabled"}
	}
	return wincom.QueryUpdates(ctx, scope)
}

type disabledUpdatesProvider struct{}

func (disabledUpdatesProvider) Name() string { return "disabled" }
func (disabledUpdatesProvider) Check(context.Context, string) (wincom.UpdateSnapshot, error) {
	return wincom.UpdateSnapshot{}, errors.New("updates provider is disabled")
}

type updatePackagePayload struct {
	Title      string  `json:"title"`
	KB         string  `json:"kb"`
	Severity   string  `json:"severity"`
	SizeMB     float64 `json:"size_mb"`
	IsSecurity bool    `json:"is_security"`
}

type updatesSnapshot struct {
	state          string
	supported      bool
	refreshing     bool
	packages       []wincom.UpdatePackage
	rebootRequired bool
	lastChecked    *time.Time
	lastError      *string
}

type updatesCache struct {
	mu       sync.RWMutex
	options  UpdatesOptions
	provider updatesProvider
	snapshot updatesSnapshot
	now      func() time.Time
	pending  <-chan providerResult
}

func newUpdatesCache(options UpdatesOptions) *updatesCache {
	if options.CheckInterval <= 0 {
		options.CheckInterval = 24 * time.Hour
	}
	if options.Timeout <= 0 {
		options.Timeout = 10 * time.Minute
	}
	if options.MaxPackages < 0 {
		options.MaxPackages = 0
	}
	provider := options.ProviderImpl
	if provider == nil {
		switch options.Provider {
		case "wua":
			provider = wuaProvider{}
		default:
			provider = disabledUpdatesProvider{}
		}
	}
	cache := &updatesCache{options: options, provider: provider, now: time.Now}
	cache.snapshot = updatesSnapshot{state: "disabled", supported: provider.Name() != "disabled", packages: []wincom.UpdatePackage{}}
	if options.Enabled && provider.Name() != "disabled" {
		cache.snapshot.state = "checking"
		cache.snapshot.supported = true
		cache.snapshot.refreshing = true
		go cache.run()
	}
	return cache
}

func (cache *updatesCache) run() {
	if terminal := cache.refresh(); terminal {
		return
	}
	ticker := time.NewTicker(cache.options.CheckInterval)
	defer ticker.Stop()
	for range ticker.C {
		cache.mu.Lock()
		cache.snapshot.refreshing = true
		cache.mu.Unlock()
		if terminal := cache.refresh(); terminal {
			return
		}
	}
}

type providerResult struct {
	snapshot wincom.UpdateSnapshot
	err      error
}

func (cache *updatesCache) refresh() bool {
	ctx, cancel := context.WithTimeout(context.Background(), cache.options.Timeout)
	defer cancel()
	if cache.pending == nil {
		completed := make(chan providerResult, 1)
		cache.pending = completed
		go func() {
			snapshot, err := cache.provider.Check(ctx, cache.options.SearchScope)
			completed <- providerResult{snapshot: snapshot, err: err}
		}()
	}
	var result providerResult
	select {
	case result = <-cache.pending:
		cache.pending = nil
	case <-ctx.Done():
		result.err = fmt.Errorf("update check timed out after %s", cache.options.Timeout)
	}
	checked := cache.now().UTC()
	cache.mu.Lock()
	defer cache.mu.Unlock()
	cache.snapshot.refreshing = false
	cache.snapshot.lastChecked = &checked
	if result.err != nil {
		message := result.err.Error()
		cache.snapshot.lastError = &message
		var unsupported unsupportedUpdatesError
		if errors.As(result.err, &unsupported) {
			cache.snapshot.state = "unsupported"
			cache.snapshot.supported = false
			return true
		}
		cache.snapshot.state = "error"
		return false
	}
	cache.snapshot.state = "idle"
	cache.snapshot.supported = true
	cache.snapshot.packages = append([]wincom.UpdatePackage(nil), result.snapshot.Packages...)
	cache.snapshot.rebootRequired = result.snapshot.RebootRequired
	cache.snapshot.lastError = nil
	return false
}

func (cache *updatesCache) data() map[string]any {
	cache.mu.RLock()
	snapshot := cache.snapshot
	snapshot.packages = append([]wincom.UpdatePackage(nil), snapshot.packages...)
	cache.mu.RUnlock()
	limit := cache.options.MaxPackages
	if limit > len(snapshot.packages) {
		limit = len(snapshot.packages)
	}
	packages := make([]updatePackagePayload, 0, limit)
	securityCount := 0
	for index, item := range snapshot.packages {
		if item.IsSecurity {
			securityCount++
		}
		if index >= limit {
			continue
		}
		packages = append(packages, updatePackagePayload{
			Title: item.Title, KB: normalizeKB(item.KB), Severity: item.Severity,
			SizeMB:     math.Round(float64(item.SizeBytes)/(1024*1024)*100) / 100,
			IsSecurity: item.IsSecurity,
		})
	}
	var checked any
	if snapshot.lastChecked != nil {
		checked = snapshot.lastChecked.Format(time.RFC3339)
	}
	var lastError any
	if snapshot.lastError != nil {
		lastError = *snapshot.lastError
	}
	return map[string]any{
		"updates_enabled":                cache.options.Enabled,
		"updates_supported":              snapshot.supported,
		"updates_provider":               cache.provider.Name(),
		"updates_state":                  snapshot.state,
		"updates_refresh_in_progress":    snapshot.refreshing,
		"updates_pending_count":          len(snapshot.packages),
		"updates_pending_security_count": securityCount,
		"updates_reboot_required":        snapshot.rebootRequired,
		"updates_last_checked_at":        checked,
		"updates_last_error":             lastError,
		"updates_check_interval_sec":     int64(cache.options.CheckInterval / time.Second),
		"updates_packages":               packages,
		"updates_packages_total":         len(snapshot.packages),
		"updates_packages_truncated":     len(snapshot.packages) > limit,
	}
}

func normalizeKB(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if strings.HasPrefix(strings.ToUpper(value), "KB") {
		return "KB" + value[2:]
	}
	return "KB" + value
}
