package power

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/sensors/maintenance"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

const ID = "power_manager"

var (
	ErrActionNotAllowed  = errors.New("action not allowed")
	ErrActionUnavailable = errors.New("action not available")
	ErrInvalidParameters = errors.New("invalid action parameters")
)

var actions = []string{"cancel", "hibernate", "lock", "restart", "shutdown", "sleep", "status"}

type auditContextKey struct{}

type AuditFunc func(action string, params map[string]any)

func WithAudit(ctx context.Context, audit AuditFunc) context.Context {
	if audit == nil {
		return ctx
	}
	return context.WithValue(ctx, auditContextKey{}, audit)
}

type Session struct {
	SessionID uint32
	User      string
	State     string
}

type Source interface {
	Available() (bool, string)
	ActiveConsoleSession() (*Session, error)
	DisconnectSession(sessionID uint32) error
	HibernateSupported() (bool, error)
	Suspend(hibernate, force bool) error
	ScheduleShutdown(reboot bool, delaySeconds uint32, force bool, message string) error
	AbortShutdown() error
	PendingReboot() (bool, error)
}

type systemSource struct{}

func (systemSource) Available() (bool, string) { return winapi.PowerActuatorAvailable() }

func (systemSource) ActiveConsoleSession() (*Session, error) {
	session, err := winapi.ActiveConsoleSession()
	if err != nil || session == nil {
		return nil, err
	}
	return &Session{SessionID: session.SessionID, User: session.User, State: session.State}, nil
}

func (systemSource) DisconnectSession(sessionID uint32) error {
	return winapi.WTSDisconnectSession(sessionID)
}

func (systemSource) HibernateSupported() (bool, error) { return winapi.HibernateSupported() }
func (systemSource) Suspend(hibernate, force bool) error {
	return winapi.SetSuspendState(hibernate, force)
}
func (systemSource) ScheduleShutdown(reboot bool, delaySeconds uint32, force bool, message string) error {
	return winapi.InitiateSystemShutdown(reboot, delaySeconds, force, message)
}
func (systemSource) AbortShutdown() error { return winapi.AbortSystemShutdown() }
func (systemSource) PendingReboot() (bool, error) {
	reasons, err := maintenance.PendingRebootReasons(winapi.NewRegistryReader())
	return len(reasons) > 0, err
}

type scheduledShutdown struct {
	Action      string
	ScheduledAt time.Time
	EffectiveAt time.Time
}

type Actuator struct {
	source       Source
	allowed      []string
	allowedSet   map[string]bool
	defaultDelay int
	now          func() time.Time
	mu           sync.RWMutex
	pending      *scheduledShutdown
}

func New(allowedActions []string, defaultDelaySeconds int, source Source) *Actuator {
	if source == nil {
		source = systemSource{}
	}
	allowed := normalizeAllowedActions(allowedActions)
	allowedSet := make(map[string]bool, len(allowed))
	for _, action := range allowed {
		allowedSet[action] = true
	}
	return &Actuator{
		source: source, allowed: allowed, allowedSet: allowedSet,
		defaultDelay: defaultDelaySeconds, now: time.Now,
	}
}

func (*Actuator) ID() string { return ID }

func (actuator *Actuator) Available() (bool, string) {
	return actuator.source.Available()
}

func (actuator *Actuator) Describe() map[string]any {
	hibernateSupported, err := actuator.source.HibernateSupported()
	if err != nil {
		hibernateSupported = false
	}
	return map[string]any{
		"actions":               append([]string(nil), actions...),
		"allowed_actions":       append([]string(nil), actuator.allowed...),
		"available_actions":     actuator.availableActions(hibernateSupported),
		"default_delay_seconds": actuator.defaultDelay,
		"hibernate_supported":   hibernateSupported,
	}
}

func (actuator *Actuator) Execute(ctx context.Context, action string, params map[string]any) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if !contains(actions, action) {
		return nil, fmt.Errorf("%w: unknown action %q", ErrActionUnavailable, action)
	}
	if !actuator.actionAllowed(action) {
		return nil, fmt.Errorf("%w: %s", ErrActionNotAllowed, action)
	}

	switch action {
	case "status":
		if err := requireNoParameters(params); err != nil {
			return nil, err
		}
		return actuator.status()
	case "lock":
		if err := requireNoParameters(params); err != nil {
			return nil, err
		}
		return actuator.lock(ctx)
	case "sleep", "hibernate":
		if err := requireNoParameters(params); err != nil {
			return nil, err
		}
		if action == "hibernate" {
			supported, err := actuator.source.HibernateSupported()
			if err != nil {
				return nil, fmt.Errorf("check hibernation support: %w", err)
			}
			if !supported {
				return nil, fmt.Errorf("%w: hibernate", ErrActionUnavailable)
			}
		}
		auditAction(ctx, action, map[string]any{"force": false})
		if err := actuator.source.Suspend(action == "hibernate", false); err != nil {
			return nil, fmt.Errorf("execute %s: %w", action, err)
		}
		return map[string]any{"ok": true, "action": action, "force": false}, nil
	case "restart", "shutdown":
		request, err := parseShutdownParameters(params, actuator.defaultDelay)
		if err != nil {
			return nil, err
		}
		return actuator.schedule(ctx, action, request)
	case "cancel":
		if err := requireNoParameters(params); err != nil {
			return nil, err
		}
		return actuator.cancel(ctx)
	default:
		panic("unhandled power action")
	}
}

func (actuator *Actuator) status() (map[string]any, error) {
	session, err := actuator.source.ActiveConsoleSession()
	if err != nil {
		return nil, fmt.Errorf("query active console session: %w", err)
	}
	hibernateSupported, err := actuator.source.HibernateSupported()
	if err != nil {
		return nil, fmt.Errorf("check hibernation support: %w", err)
	}
	pendingReboot, err := actuator.source.PendingReboot()
	if err != nil {
		return nil, fmt.Errorf("query pending reboot: %w", err)
	}
	actuator.mu.RLock()
	shutdownPending := actuator.pending != nil
	actuator.mu.RUnlock()
	var activeSession any
	if session != nil {
		activeSession = map[string]any{
			"session_id": session.SessionID,
			"user":       session.User,
			"state":      session.State,
		}
	}
	return map[string]any{
		"ok":                     true,
		"allowed_actions":        append([]string(nil), actuator.allowed...),
		"available_actions":      actuator.availableActions(hibernateSupported),
		"hibernate_supported":    hibernateSupported,
		"shutdown_pending":       shutdownPending,
		"active_console_session": activeSession,
		"pending_reboot":         pendingReboot,
	}, nil
}

func (actuator *Actuator) lock(ctx context.Context) (map[string]any, error) {
	session, err := actuator.source.ActiveConsoleSession()
	if err != nil {
		return nil, fmt.Errorf("query active console session: %w", err)
	}
	response := map[string]any{"ok": true, "action": "lock", "method": "wts_disconnect"}
	if session == nil || session.State != "active" {
		response["message"] = "no active console session"
		return response, nil
	}
	auditAction(ctx, "lock", map[string]any{
		"method": "wts_disconnect", "session_id": session.SessionID,
	})
	if err := actuator.source.DisconnectSession(session.SessionID); err != nil {
		return nil, fmt.Errorf("disconnect console session %d: %w", session.SessionID, err)
	}
	response["session_id"] = session.SessionID
	return response, nil
}

type shutdownParameters struct {
	DelaySeconds int
	Force        bool
	Message      string
}

func (actuator *Actuator) schedule(ctx context.Context, action string, request shutdownParameters) (map[string]any, error) {
	now := actuator.now().UTC()
	auditAction(ctx, action, map[string]any{
		"delay_seconds": request.DelaySeconds, "force": request.Force, "message": request.Message,
	})
	if err := actuator.source.ScheduleShutdown(action == "restart", uint32(request.DelaySeconds), request.Force, request.Message); err != nil {
		return nil, fmt.Errorf("schedule %s: %w", action, err)
	}
	effective := now.Add(time.Duration(request.DelaySeconds) * time.Second)
	actuator.mu.Lock()
	actuator.pending = &scheduledShutdown{Action: action, ScheduledAt: now, EffectiveAt: effective}
	actuator.mu.Unlock()
	return map[string]any{
		"ok": true, "action": action, "delay_seconds": request.DelaySeconds,
		"force": request.Force, "scheduled_at": now.Format(time.RFC3339),
		"effective_at": effective.Format(time.RFC3339), "cancellable": true,
	}, nil
}

func (actuator *Actuator) cancel(ctx context.Context) (map[string]any, error) {
	auditAction(ctx, "cancel", map[string]any{})
	if err := actuator.source.AbortShutdown(); err != nil {
		return nil, fmt.Errorf("cancel shutdown: %w", err)
	}
	actuator.mu.Lock()
	actuator.pending = nil
	actuator.mu.Unlock()
	return map[string]any{"ok": true, "action": "cancel"}, nil
}

func auditAction(ctx context.Context, action string, params map[string]any) {
	audit, _ := ctx.Value(auditContextKey{}).(AuditFunc)
	if audit != nil {
		audit(action, params)
	}
}

func (actuator *Actuator) actionAllowed(action string) bool {
	switch action {
	case "status":
		return true
	case "cancel":
		return actuator.allowedSet["restart"] || actuator.allowedSet["shutdown"]
	default:
		return actuator.allowedSet[action]
	}
}

func (actuator *Actuator) availableActions(hibernateSupported bool) []string {
	available := make([]string, 0, len(actuator.allowed)+2)
	for _, action := range actuator.allowed {
		if action != "hibernate" || hibernateSupported {
			available = append(available, action)
		}
	}
	if actuator.allowedSet["restart"] || actuator.allowedSet["shutdown"] {
		available = append(available, "cancel")
	}
	return append(available, "status")
}

func normalizeAllowedActions(values []string) []string {
	seen := make(map[string]bool, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		if !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}

func parseShutdownParameters(params map[string]any, defaultDelay int) (shutdownParameters, error) {
	result := shutdownParameters{DelaySeconds: defaultDelay}
	for key := range params {
		switch key {
		case "delay_seconds", "force", "message":
		default:
			return shutdownParameters{}, fmt.Errorf("%w: unknown field %q", ErrInvalidParameters, key)
		}
	}
	if value, ok := params["delay_seconds"]; ok {
		delay, valid := integerValue(value)
		if !valid || delay < 0 || delay > 86400 {
			return shutdownParameters{}, fmt.Errorf("%w: delay_seconds must be an integer between 0 and 86400", ErrInvalidParameters)
		}
		result.DelaySeconds = delay
	}
	if value, ok := params["force"]; ok {
		force, valid := value.(bool)
		if !valid {
			return shutdownParameters{}, fmt.Errorf("%w: force must be a boolean", ErrInvalidParameters)
		}
		result.Force = force
	}
	if value, ok := params["message"]; ok {
		message, valid := value.(string)
		if !valid {
			return shutdownParameters{}, fmt.Errorf("%w: message must be a string", ErrInvalidParameters)
		}
		result.Message = message
	}
	return result, nil
}

func requireNoParameters(params map[string]any) error {
	if len(params) != 0 {
		keys := make([]string, 0, len(params))
		for key := range params {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		return fmt.Errorf("%w: action does not accept field %q", ErrInvalidParameters, keys[0])
	}
	return nil
}

func integerValue(value any) (int, bool) {
	switch number := value.(type) {
	case int:
		return number, true
	case float64:
		if math.Trunc(number) == number && number >= math.MinInt && number <= math.MaxInt {
			return int(number), true
		}
	case json.Number:
		parsed, err := number.Int64()
		if err == nil && parsed >= math.MinInt && parsed <= math.MaxInt {
			return int(parsed), true
		}
	}
	return 0, false
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
