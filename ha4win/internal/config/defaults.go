package config

import "runtime"

const (
	WindowsDefaultConfigPath = `C:\ProgramData\HA4Win\config.json`
	WindowsDefaultCertPath   = `C:\ProgramData\HA4Win\certs\ha4win.crt`
	WindowsDefaultKeyPath    = `C:\ProgramData\HA4Win\certs\ha4win.key`
)

func DefaultPath() string {
	if runtime.GOOS == "windows" {
		return WindowsDefaultConfigPath
	}
	return "./config.json"
}

func Defaults() Config {
	return Config{
		API: APIConfig{BindHost: "0.0.0.0", BindPort: 8099, AllowedClients: []string{}, SensorTimeoutSec: 3},
		TLS: TLSConfig{
			Enabled:  true,
			CertFile: WindowsDefaultCertPath,
			KeyFile:  WindowsDefaultKeyPath,
			SelfSigned: SelfSignedConfig{
				AutoGenerate: true, ValidDays: 3650, SubjectAltNames: []string{},
			},
		},
		Modules: ModulesConfig{
			CPU:    CPUConfig{Enabled: true, PerCore: true},
			Memory: EnabledConfig{Enabled: true},
			Network: NetworkConfig{
				Enabled: true, ExcludeInterfaces: []string{"Loopback*", "isatap*", "Teredo*", "vEthernet*", "VirtualBox*", "VMware*"}, AggregateMode: "selected", IncludeInterfaces: []string{},
			},
			Volumes:  VolumesConfig{Enabled: true, IncludeDriveTypes: []string{"fixed"}, ExcludeMounts: []string{}},
			Services: ServicesConfig{Enabled: false, Watchlist: []string{}},
			SystemInfo: SystemInfoConfig{
				Enabled: true, UpdatesEnabled: true, UpdatesProvider: "wua", UpdatesSearchScope: "default", UpdatesCheckIntervalSec: 86400, UpdatesTimeoutSec: 600, UpdatesMaxPackages: 25,
			},
			Maintenance: EnabledConfig{Enabled: true},
			Security:    SecurityConfig{Enabled: true, Defender: true, Firewall: true, BitLocker: false, RefreshIntervalSec: 300},
		},
		Actuators: ActuatorsConfig{Power: PowerConfig{Enabled: true, AllowedActions: []string{"lock"}, DefaultDelaySeconds: 30}},
		Management: ManagementConfig{RemoteUpdate: RemoteUpdateConfig{
			Enabled: false, Channel: "stable", CheckIntervalSec: 1800, CheckTimeoutSec: 10, ApplyTimeoutSec: 300, HealthCheckTimeoutSec: 60,
		}},
		Logging: LoggingConfig{Level: "info", FileEnabled: true, MaxSizeMB: 10, MaxFiles: 5, EventLogEnabled: true},
	}
}
