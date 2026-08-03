package registry

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"
)

var (
	ErrActuatorNotFound = errors.New("actuator not found")
	ErrActuatorPanic    = errors.New("actuator panic")
)

type Logger interface {
	Info(string)
}

type SensorResult struct {
	Enabled   bool           `json:"enabled"`
	Available bool           `json:"available"`
	Data      map[string]any `json:"data,omitempty"`
	Reason    string         `json:"reason,omitempty"`
}

type Registry struct {
	mu        sync.RWMutex
	sensors   map[string]Sensor
	actuators map[string]Actuator
	timeout   time.Duration
	logger    Logger
}

func New(timeout time.Duration, logger Logger) *Registry {
	if timeout <= 0 {
		timeout = 3 * time.Second
	}
	return &Registry{
		sensors:   make(map[string]Sensor),
		actuators: make(map[string]Actuator),
		timeout:   timeout,
		logger:    logger,
	}
}

func (r *Registry) RegisterSensor(sensor Sensor) bool {
	if sensor == nil {
		return false
	}
	id := sensor.ID()
	if id == "" {
		r.log("Skipping sensor with empty ID")
		return false
	}
	if probe, ok := sensor.(Probe); ok {
		available, reason := safeProbe(probe)
		if !available {
			if reason == "" {
				reason = "prerequisite is not available"
			}
			r.log(fmt.Sprintf("Skipping sensor %q: %s", id, reason))
			return false
		}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.sensors[id]; exists {
		r.log(fmt.Sprintf("Skipping duplicate sensor %q", id))
		return false
	}
	r.sensors[id] = sensor
	return true
}

func (r *Registry) RegisterActuator(actuator Actuator) bool {
	if actuator == nil {
		return false
	}
	id := actuator.ID()
	if id == "" {
		r.log("Skipping actuator with empty ID")
		return false
	}
	if probe, ok := actuator.(Probe); ok {
		available, reason := safeProbe(probe)
		if !available {
			if reason == "" {
				reason = "prerequisite is not available"
			}
			r.log(fmt.Sprintf("Skipping actuator %q: %s", id, reason))
			return false
		}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.actuators[id]; exists {
		r.log(fmt.Sprintf("Skipping duplicate actuator %q", id))
		return false
	}
	r.actuators[id] = actuator
	return true
}

func safeProbe(probe Probe) (available bool, reason string) {
	defer func() {
		if recovered := recover(); recovered != nil {
			available = false
			reason = fmt.Sprintf("probe panic: %v", recovered)
		}
	}()
	return probe.Available()
}

func (r *Registry) SensorIDs() []string {
	r.mu.RLock()
	ids := make([]string, 0, len(r.sensors))
	for id := range r.sensors {
		ids = append(ids, id)
	}
	r.mu.RUnlock()
	sort.Strings(ids)
	return ids
}

func (r *Registry) ActuatorIDs() []string {
	r.mu.RLock()
	ids := make([]string, 0, len(r.actuators))
	for id := range r.actuators {
		ids = append(ids, id)
	}
	r.mu.RUnlock()
	sort.Strings(ids)
	return ids
}

func (r *Registry) ActuatorCapabilities() map[string]any {
	r.mu.RLock()
	actuators := make(map[string]Actuator, len(r.actuators))
	for id, actuator := range r.actuators {
		actuators[id] = actuator
	}
	r.mu.RUnlock()

	details := make(map[string]any, len(actuators))
	for id, actuator := range actuators {
		description, err := describeActuator(actuator)
		if err != nil {
			r.log(fmt.Sprintf("Actuator %q description failed: %v", id, err))
			details[id] = map[string]any{"available": false, "reason": err.Error()}
			continue
		}
		details[id] = description
	}
	return details
}

func describeActuator(actuator Actuator) (description map[string]any, err error) {
	defer func() {
		if recovered := recover(); recovered != nil {
			err = fmt.Errorf("%w: %v", ErrActuatorPanic, recovered)
		}
	}()
	description = actuator.Describe()
	if description == nil {
		description = map[string]any{}
	}
	return description, nil
}

func (r *Registry) ExecuteActuator(ctx context.Context, id, action string, params map[string]any) (result map[string]any, err error) {
	r.mu.RLock()
	actuator, exists := r.actuators[id]
	r.mu.RUnlock()
	if !exists {
		return nil, fmt.Errorf("%w: %s", ErrActuatorNotFound, id)
	}
	defer func() {
		if recovered := recover(); recovered != nil {
			err = fmt.Errorf("%w: %v", ErrActuatorPanic, recovered)
			result = nil
		}
	}()
	result, err = actuator.Execute(ctx, action, params)
	if result == nil && err == nil {
		result = map[string]any{}
	}
	return result, err
}

func (r *Registry) Collect(ctx context.Context) map[string]SensorResult {
	r.mu.RLock()
	sensors := make(map[string]Sensor, len(r.sensors))
	for id, sensor := range r.sensors {
		sensors[id] = sensor
	}
	r.mu.RUnlock()

	results := make(map[string]SensorResult, len(sensors))
	var resultsMu sync.Mutex
	var wait sync.WaitGroup
	for id, sensor := range sensors {
		wait.Add(1)
		go func(id string, sensor Sensor) {
			defer wait.Done()
			result := r.collectOne(ctx, sensor)
			resultsMu.Lock()
			results[id] = result
			resultsMu.Unlock()
		}(id, sensor)
	}
	wait.Wait()
	return results
}

type collection struct {
	data map[string]any
	err  error
}

func (r *Registry) collectOne(parent context.Context, sensor Sensor) SensorResult {
	ctx, cancel := context.WithTimeout(parent, r.timeout)
	defer cancel()
	completed := make(chan collection, 1)
	go func() {
		result := collection{}
		defer func() {
			if recovered := recover(); recovered != nil {
				result.err = fmt.Errorf("panic: %v", recovered)
			}
			completed <- result
		}()
		result.data, result.err = sensor.Collect(ctx)
	}()
	select {
	case result := <-completed:
		if result.err != nil {
			if errors.Is(result.err, context.DeadlineExceeded) && ctx.Err() != nil && parent.Err() == nil {
				return SensorResult{Enabled: true, Available: false, Reason: fmt.Sprintf("timeout after %s", r.timeout)}
			}
			return SensorResult{Enabled: true, Available: false, Reason: result.err.Error()}
		}
		if result.data == nil {
			result.data = map[string]any{}
		}
		return SensorResult{Enabled: true, Available: true, Data: result.data}
	case <-ctx.Done():
		if parent.Err() != nil {
			return SensorResult{Enabled: true, Available: false, Reason: parent.Err().Error()}
		}
		return SensorResult{Enabled: true, Available: false, Reason: fmt.Sprintf("timeout after %s", r.timeout)}
	}
}

func (r *Registry) log(message string) {
	if r.logger != nil {
		r.logger.Info(message)
	}
}
