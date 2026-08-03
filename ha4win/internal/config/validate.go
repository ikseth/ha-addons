package config

import (
	"fmt"
	"net"
	"net/netip"
	"os"
	"strings"
)

type Validation struct {
	Warnings []string
}

func Validate(cfg Config) (Validation, error) {
	warnings := make([]string, 0)
	if cfg.API.Token == "" {
		return Validation{}, fmt.Errorf("api.token must not be empty")
	}
	if len(cfg.API.Token) < 24 {
		warnings = append(warnings, "api.token is shorter than 24 characters")
	}
	if cfg.API.BindPort < 1 || cfg.API.BindPort > 65535 {
		return Validation{}, fmt.Errorf("api.bind_port must be between 1 and 65535")
	}
	if strings.TrimSpace(cfg.API.BindHost) == "" {
		return Validation{}, fmt.Errorf("api.bind_host must not be empty")
	}
	for index, cidr := range cfg.API.AllowedClients {
		if _, err := netip.ParsePrefix(cidr); err != nil {
			return Validation{}, fmt.Errorf("api.allowed_clients[%d] is not a valid CIDR: %q", index, cidr)
		}
	}
	if cfg.API.SensorTimeoutSec <= 0 {
		return Validation{}, fmt.Errorf("api.sensor_timeout_sec must be greater than zero")
	}
	if cfg.TLS.Enabled {
		certExists := fileExists(cfg.TLS.CertFile)
		keyExists := fileExists(cfg.TLS.KeyFile)
		if certExists != keyExists {
			return Validation{}, fmt.Errorf("tls.certfile and tls.keyfile must either both exist or both be absent")
		}
		if !certExists && !cfg.TLS.SelfSigned.AutoGenerate {
			return Validation{}, fmt.Errorf("TLS files do not exist and tls.self_signed.auto_generate is false")
		}
		if cfg.TLS.SelfSigned.ValidDays <= 0 {
			return Validation{}, fmt.Errorf("tls.self_signed.valid_days must be greater than zero")
		}
	} else if !IsLoopbackBind(cfg.API.BindHost) {
		warnings = append(warnings, "TLS is disabled while api.bind_host is not loopback")
	}
	if cfg.Modules.Network.AggregateMode != "selected" && cfg.Modules.Network.AggregateMode != "all" {
		return Validation{}, fmt.Errorf("modules.network.aggregate_mode must be selected or all")
	}
	validDriveTypes := map[string]bool{"fixed": true, "removable": true, "network": true, "cdrom": true, "ramdisk": true}
	for _, driveType := range cfg.Modules.Volumes.IncludeDriveTypes {
		if !validDriveTypes[driveType] {
			return Validation{}, fmt.Errorf("modules.volumes.include_drive_types contains unknown value %q", driveType)
		}
	}
	if cfg.Modules.Services.Enabled && len(cfg.Modules.Services.Watchlist) == 0 {
		warnings = append(warnings, "modules.services is enabled with an empty watchlist and will not be registered")
	}
	if !cfg.ReadonlyMode {
		validActions := map[string]bool{"lock": true, "sleep": true, "hibernate": true, "restart": true, "shutdown": true}
		for _, action := range cfg.Actuators.Power.AllowedActions {
			if !validActions[action] {
				return Validation{}, fmt.Errorf("actuators.power.allowed_actions contains unknown action %q", action)
			}
		}
		if cfg.Actuators.Power.DefaultDelaySeconds < 0 || cfg.Actuators.Power.DefaultDelaySeconds > 86400 {
			return Validation{}, fmt.Errorf("actuators.power.default_delay_seconds must be between 0 and 86400")
		}
	}
	if cfg.Management.RemoteUpdate.Enabled && strings.TrimSpace(cfg.Management.RemoteUpdate.ManifestURL) == "" {
		return Validation{}, fmt.Errorf("management.remote_update.manifest_url is required when remote update is enabled")
	}
	if cfg.Logging.MaxSizeMB <= 0 || cfg.Logging.MaxFiles < 1 {
		return Validation{}, fmt.Errorf("logging.max_size_mb and logging.max_files must be greater than zero")
	}
	switch cfg.Logging.Level {
	case "debug", "info", "warning", "error":
	default:
		return Validation{}, fmt.Errorf("logging.level must be debug, info, warning, or error")
	}
	return Validation{Warnings: warnings}, nil
}

func IsLoopbackBind(host string) bool {
	host = strings.TrimSpace(host)
	if zone := strings.LastIndexByte(host, '%'); zone >= 0 {
		host = host[:zone]
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
