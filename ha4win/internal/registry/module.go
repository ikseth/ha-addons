package registry

import "context"

type Sensor interface {
	ID() string
	Collect(ctx context.Context) (map[string]any, error)
}

type Actuator interface {
	ID() string
	Describe() map[string]any
	Execute(ctx context.Context, action string, params map[string]any) (map[string]any, error)
}

type Probe interface {
	Available() (bool, string)
}
