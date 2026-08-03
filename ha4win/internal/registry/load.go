package registry

import (
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/sensors/cpu"
	"github.com/ikseth/ha-addons/ha4win/internal/sensors/memory"
	"github.com/ikseth/ha-addons/ha4win/internal/sensors/network"
	"github.com/ikseth/ha-addons/ha4win/internal/sensors/services"
	"github.com/ikseth/ha-addons/ha4win/internal/sensors/systeminfo"
	"github.com/ikseth/ha-addons/ha4win/internal/sensors/volumes"
)

func Load(cfg config.Config, logger Logger) *Registry {
	registry := New(time.Duration(cfg.API.SensorTimeoutSec)*time.Second, logger)
	if cfg.Modules.CPU.Enabled {
		registry.RegisterSensor(cpu.New(cfg.Modules.CPU.PerCore, nil))
	}
	if cfg.Modules.Memory.Enabled {
		registry.RegisterSensor(memory.New(nil))
	}
	if cfg.Modules.Network.Enabled {
		registry.RegisterSensor(network.New(
			cfg.Modules.Network.IncludeInterfaces,
			cfg.Modules.Network.ExcludeInterfaces,
			cfg.Modules.Network.AggregateMode,
			nil,
		))
	}
	if cfg.Modules.Volumes.Enabled {
		registry.RegisterSensor(volumes.New(
			cfg.Modules.Volumes.IncludeDriveTypes,
			cfg.Modules.Volumes.ExcludeMounts,
			nil,
		))
	}
	if cfg.Modules.Services.Enabled {
		registry.RegisterSensor(services.New(cfg.Modules.Services.Watchlist, nil))
	}
	if cfg.Modules.SystemInfo.Enabled {
		registry.RegisterSensor(systeminfo.New(nil))
	}
	return registry
}
